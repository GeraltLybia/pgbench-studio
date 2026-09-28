"""RunManager: starts pgbench as a child process and tracks its lifecycle.

`pgbench -i` (kind=init) and benchmark runs (kind=bench). Every line, progress point,
agent sample and status change goes to the run's event bus, which the WebSocket streams.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import signal
import tempfile
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Literal

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.command import InitOptions, build_init_argv
from app.core.connection import ConnParams
from app.core.events import EventHub, RunEvents
from app.core.parsers.progress import (
    InitProgress,
    ProgressEstimator,
    parse_bench_progress,
    parse_init_phase,
    parse_init_progress,
)
from app.core.report import ReportOptions, RunReport, abort_reason, build_report
from app.metrics.agent import AgentSample, CpuWarning, run_sampler, sample
from app.storage.models import (
    Run,
    RunHistogram,
    RunKind,
    RunSeries,
    RunStatement,
    RunStatus,
    utcnow,
)

log = logging.getLogger(__name__)

LOG_BUFFER_LINES = 2000
_LINE_SPLIT = re.compile(rb"\r\n|\r|\n")
RESTART_ERROR = "Агент перезапущен во время выполнения"
# Cancel: SIGINT, then SIGTERM, then SIGKILL, each after this many seconds.
CANCEL_STEP_S = 5.0

Stream = Literal["stdout", "stderr"]


class RunLimitError(Exception):
    """The agent already runs as many processes as max_parallel_runs allows."""


class RunNotActiveError(Exception):
    """The run is not running on this agent (finished, unknown, or before a restart)."""


@dataclass(frozen=True)
class AgentOptions:
    name: str = "load-agent-01"
    sample_interval_s: float = 1.0
    cpu_warning_percent: int = 85


@dataclass(frozen=True)
class ProgressPlan:
    """What `pct` and `eta_s` are computed against."""

    mode: str
    duration_s: int | None = None
    clients: int = 1
    transactions: int | None = None


@dataclass(frozen=True)
class LogLine:
    stream: Stream
    line: str


@dataclass
class ActiveRun:
    run_id: int
    kind: RunKind
    log: deque[LogLine] = field(default_factory=lambda: deque(maxlen=LOG_BUFFER_LINES))
    init_progress: InitProgress | None = None
    phase: str | None = None
    process: asyncio.subprocess.Process | None = None
    task: asyncio.Task[None] | None = None
    events: RunEvents | None = None
    estimator: ProgressEstimator | None = None
    cancelled_by: str | None = None
    started_monotonic: float = 0.0
    sampler: asyncio.Task[None] | None = None
    report_options: ReportOptions | None = None


def child_env(params: ConnParams, run_dir: Path) -> dict[str, str]:
    """Minimal environment: no agent secrets, C locale for stable output, no ~/.pgpass."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LC_ALL": "C",
        "HOME": str(run_dir),
        **params.libpq_env(),
    }


def public_params(params: ConnParams) -> dict[str, object]:
    data = asdict(params)
    data.pop("password")
    return data


def write_files(directory: Path, files: dict[str, str]) -> None:
    """Script files; names come from command.script_file_names, never from user input."""
    for name, body in files.items():
        path = directory / name
        if path.parent != directory:  # pragma: no cover - defence against path tricks
            raise ValueError(f"unsafe script file name: {name}")
        path.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")


@dataclass(frozen=True)
class DryRun:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool


async def run_dry(
    argv: list[str],
    files: dict[str, str],
    params: ConnParams,
    work_root: Path,
    timeout_s: float = 60,
) -> DryRun:
    """`pgbench -c 1 -t 1 -n` in a scratch directory, removed afterwards; no run record."""
    await asyncio.to_thread(work_root.mkdir, parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="dry-", dir=work_root))
    started = time.perf_counter()
    try:
        write_files(work, files)
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work,
            env=child_env(params, work),
        )
        try:
            out, err = await asyncio.wait_for(process.communicate(), timeout_s)
        except TimeoutError:
            process.kill()
            out, err = await process.communicate()
            return DryRun(
                None,
                out.decode(errors="replace"),
                err.decode(errors="replace"),
                (time.perf_counter() - started) * 1000,
                True,
            )
        return DryRun(
            process.returncode,
            out.decode(errors="replace"),
            err.decode(errors="replace"),
            (time.perf_counter() - started) * 1000,
            False,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


class RunManager:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        runs_dir: Path,
        max_parallel: int,
        pgbench_binary: str,
        *,
        hub: EventHub | None = None,
        agent: AgentOptions | None = None,
        agent_sampler: Callable[[], AgentSample] = sample,
        cancel_step_s: float = CANCEL_STEP_S,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._runs_dir = runs_dir
        self._max_parallel = max_parallel
        self._binary = pgbench_binary
        self._active: dict[int, ActiveRun] = {}
        self._lock = asyncio.Lock()
        self.hub = hub or EventHub()
        self.agent = agent or AgentOptions()
        self._agent_sampler = agent_sampler
        self._cancel_step_s = cancel_step_s

    def get_active(self, run_id: int) -> ActiveRun | None:
        return self._active.get(run_id)

    @property
    def active_ids(self) -> list[int]:
        return list(self._active)

    async def recover(self) -> int:
        """Mark runs left active by a previous process as failed."""
        async with self._sessionmaker() as db:
            active = [s.value for s in RunStatus if s.is_active]
            result = await db.execute(select(Run).where(Run.status.in_(active)))
            runs = list(result.scalars())
            for run in runs:
                run.status = RunStatus.failed.value
                run.error = RESTART_ERROR
                run.finished_at = run.finished_at or utcnow()
            await db.commit()
        if runs:
            log.warning("runs marked failed after restart", extra={"runs": [r.id for r in runs]})
        return len(runs)

    async def stuck_runs(self) -> list[int]:
        """Runs the database says are active but that have no process on this agent."""
        async with self._sessionmaker() as db:
            active = [s.value for s in RunStatus if s.is_active]
            result = await db.execute(select(Run.id).where(Run.status.in_(active)))
            ids = [int(i) for i in result.scalars()]
        return [i for i in ids if i not in self._active]

    async def start_init(
        self,
        *,
        profile_id: int,
        params: ConnParams,
        options: InitOptions,
        started_by: str,
        pgbench_version: str | None,
        server_version: str | None,
    ) -> int:
        argv = build_init_argv(self._binary, options)
        config: dict[str, object] = {
            "kind": "init",
            "connection": public_params(params),
            "init": asdict(options),
        }
        return await self._start(
            kind=RunKind.init,
            profile_id=profile_id,
            params=params,
            argv=argv,
            files={},
            config=config,
            summary={"kind": "init", "argv": argv},
            plan=None,
            confirmed_rules=None,
            started_by=started_by,
            pgbench_version=pgbench_version,
            server_version=server_version,
        )

    async def start_bench(
        self,
        *,
        profile_id: int,
        params: ConnParams,
        argv: list[str],
        files: dict[str, str],
        config: dict[str, object],
        confirmed_rules: list[str],
        started_by: str,
        pgbench_version: str | None,
        server_version: str | None,
        plan: ProgressPlan | None = None,
        summary: dict[str, Any] | None = None,
        report: ReportOptions | None = None,
    ) -> int:
        return await self._start(
            kind=RunKind.bench,
            profile_id=profile_id,
            params=params,
            argv=argv,
            files=files,
            config=config,
            summary={"kind": "bench", "argv": argv, **(summary or {})},
            plan=plan,
            report=report or ReportOptions(),
            confirmed_rules=confirmed_rules,
            started_by=started_by,
            pgbench_version=pgbench_version,
            server_version=server_version,
        )

    async def _start(
        self,
        *,
        kind: RunKind,
        profile_id: int,
        params: ConnParams,
        argv: list[str],
        files: dict[str, str],
        config: dict[str, object],
        summary: dict[str, Any],
        plan: ProgressPlan | None,
        confirmed_rules: list[str] | None,
        started_by: str,
        pgbench_version: str | None,
        server_version: str | None,
        report: ReportOptions | None = None,
    ) -> int:
        async with self._lock:
            if len(self._active) >= self._max_parallel:
                raise RunLimitError
            async with self._sessionmaker() as db:
                run = Run(
                    profile_id=profile_id,
                    kind=kind.value,
                    status=RunStatus.queued.value,
                    started_by=started_by,
                    config_json=json.dumps(config, ensure_ascii=False),
                    argv_json=json.dumps(argv),
                    confirmed_rules_json=(
                        json.dumps(confirmed_rules, ensure_ascii=False)
                        if confirmed_rules is not None
                        else None
                    ),
                    pgbench_version=pgbench_version,
                    server_version=server_version,
                )
                db.add(run)
                await db.commit()
                run_id = run.id
            active = ActiveRun(run_id=run_id, kind=kind, report_options=report)
            if plan is not None:
                active.estimator = ProgressEstimator(
                    plan.mode, plan.duration_s, plan.clients, plan.transactions
                )
            active.events = self.hub.open(
                run_id,
                {
                    **summary,
                    "run_id": run_id,
                    "started_by": started_by,
                    "agent_name": self.agent.name,
                    "server_version": server_version,
                    "pgbench_version": pgbench_version,
                    "estimated": active.estimator.estimated if active.estimator else None,
                },
            )
            self._active[run_id] = active
            self._status(active, RunStatus.queued)

        run_dir = self._runs_dir / str(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        write_files(run_dir, files)
        try:
            # Argument list only, never a shell; the password is in env (PGPASSWORD).
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=run_dir,
                env=child_env(params, run_dir),
            )
        except OSError as exc:
            await self._finish(active, RunStatus.failed, f"Не удалось запустить pgbench: {exc}")
            return run_id

        active.process = process
        active.started_monotonic = time.monotonic()
        started_at = await self._update(run_id, status=RunStatus.running, started_at=True)
        if active.events is not None and started_at is not None:
            active.events.config["started_at"] = started_at.isoformat()
        self._status(active, RunStatus.running)
        if kind is RunKind.bench:
            active.sampler = asyncio.create_task(self._sample_agent(active))
        active.task = asyncio.create_task(self._supervise(active, process, run_dir))
        log.info("run started", extra={"run_id": run_id, "kind": kind.value, "user": started_by})
        return run_id

    def _status(
        self,
        active: ActiveRun,
        status: RunStatus,
        exit_code: int | None = None,
        error: str | None = None,
    ) -> None:
        if active.events is not None:
            active.events.publish(
                "status",
                status=status.value,
                exit_code=exit_code,
                error=error,
                stopped_by=active.cancelled_by,
            )

    async def _sample_agent(self, active: ActiveRun) -> None:
        warning = CpuWarning(self.agent.cpu_warning_percent)

        async def publish(sample_: AgentSample) -> None:
            if active.events is None:
                return
            active.events.publish(
                "resources",
                source=self.agent.name,
                t=round(time.monotonic() - active.started_monotonic, 1),
                cpu_pct=sample_.cpu_pct,
                ram_pct=sample_.ram_pct,
                ram_used_bytes=sample_.ram_used_bytes,
                ram_total_bytes=sample_.ram_total_bytes,
            )
            if warning.check(sample_.cpu_pct):
                active.events.publish(
                    "warning",
                    code="agent_cpu_high",
                    message=(
                        f"CPU агента выше {self.agent.cpu_warning_percent} %: упор в генератор "
                        "нагрузки, а не в базу. Уменьшите -j или -c либо используйте агент мощнее."
                    ),
                )

        await run_sampler(self.agent.sample_interval_s, publish, self._agent_sampler)

    async def _supervise(
        self, active: ActiveRun, process: asyncio.subprocess.Process, run_dir: Path
    ) -> None:
        assert process.stdout is not None and process.stderr is not None  # noqa: S101
        with (
            (run_dir / "stdout.log").open("w", encoding="utf-8") as out,
            (run_dir / "stderr.log").open("w", encoding="utf-8") as err,
        ):
            await asyncio.gather(
                self._pump(active, "stdout", process.stdout, out),
                self._pump(active, "stderr", process.stderr, err),
            )
        code = await process.wait()
        if active.sampler is not None:
            active.sampler.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await active.sampler

        await self._update(active.run_id, status=RunStatus.finalizing)
        self._status(active, RunStatus.finalizing, exit_code=code)
        summary: dict[str, object] = {"exit_code": code}
        if active.report_options is not None:
            summary |= await self._build_report(active.run_id, run_dir, active.report_options)

        if active.cancelled_by is not None:
            await self._finish(active, RunStatus.cancelled, "Остановлен пользователем", summary)
        elif code == 0:
            await self._finish(active, RunStatus.completed, None, summary)
        else:
            stderr = [e.line for e in active.log if e.stream == "stderr"]
            reason = abort_reason(stderr) or (stderr[-1] if stderr else None)
            await self._finish(
                active, RunStatus.failed, reason or f"pgbench завершился с кодом {code}", summary
            )

    async def _build_report(
        self, run_id: int, run_dir: Path, options: ReportOptions
    ) -> dict[str, object]:
        """Parse the run directory and store series, -r rows and the histogram."""
        report: RunReport = await asyncio.to_thread(build_report, run_dir, options)
        async with self._sessionmaker() as db:
            if report.series:
                await db.execute(
                    insert(RunSeries),
                    [
                        {
                            "run_id": run_id,
                            "t_s": p.t_s,
                            "tx": p.tx,
                            "tps": p.tps,
                            "lat_avg_ms": p.lat_avg_ms,
                            "lat_min_ms": p.lat_min_ms,
                            "lat_max_ms": p.lat_max_ms,
                            "lat_std_ms": p.lat_std_ms,
                            "lag_ms": p.lag_ms,
                            "failed": p.failed,
                            "retried": p.retried,
                        }
                        for p in report.series
                    ],
                )
            statements = report.statements(options.scripts)
            if statements:
                await db.execute(
                    insert(RunStatement),
                    [
                        {
                            "run_id": run_id,
                            "script": name[:128],
                            "idx": st.idx,
                            "sql": st.command,
                            "latency_ms": st.latency_ms,
                            "failures": st.failures,
                        }
                        for name, st in statements
                    ],
                )
            if report.histogram:
                await db.execute(
                    insert(RunHistogram),
                    [
                        {"run_id": run_id, "bucket_upper_ms": upper, "count": count}
                        for upper, count in report.histogram
                    ],
                )
            await db.commit()
        return report.summary_json(options)

    async def _pump(
        self, active: ActiveRun, stream: Stream, reader: asyncio.StreamReader, sink: IO[str]
    ) -> None:
        buffer = b""
        while chunk := await reader.read(4096):
            buffer += chunk
            *lines, buffer = _LINE_SPLIT.split(buffer)
            for raw in lines:
                self._on_line(active, stream, raw.decode(errors="replace"), sink)
        if buffer:
            self._on_line(active, stream, buffer.decode(errors="replace"), sink)

    @staticmethod
    def _on_line(active: ActiveRun, stream: Stream, line: str, sink: IO[str]) -> None:
        if not line:
            return
        sink.write(line + "\n")
        sink.flush()
        active.log.append(LogLine(stream, line))
        events = active.events
        if events is not None:
            events.publish("log", stream=stream, line=line)
        if active.kind is RunKind.init:
            progress = parse_init_progress(line)
            if progress is not None:
                active.init_progress = progress
            phase = parse_init_phase(line)
            if phase is not None:
                active.phase = phase
            return
        bench = parse_bench_progress(line)
        if bench is not None and events is not None:
            pct, eta = active.estimator.update(bench) if active.estimator else (None, None)
            events.publish(
                "progress",
                t=bench.t,
                tps=bench.tps,
                lat_ms=bench.lat_ms,
                stddev_ms=bench.stddev_ms,
                lag_ms=bench.lag_ms,
                failed=bench.failed,
                skipped=bench.skipped,
                retried=bench.retried,
                pct=pct,
                eta_s=eta,
            )

    async def cancel(self, run_id: int, username: str) -> None:
        """Stop a run: SIGINT, SIGTERM after 5 s, SIGKILL after 5 more (at most ~10 s)."""
        active = self._active.get(run_id)
        if active is None or active.process is None or active.process.returncode is not None:
            raise RunNotActiveError
        if active.cancelled_by is not None:
            return
        active.cancelled_by = username
        async with self._sessionmaker() as db:
            run = await db.get(Run, run_id)
            if run is not None:
                run.stopped_by = username
                await db.commit()
        if active.events is not None:
            active.events.publish("log", stream="stderr", line=f"Остановка по запросу {username}")
        asyncio.create_task(self._escalate(active.process))  # noqa: RUF006 - ends with the process
        log.info("run cancel requested", extra={"run_id": run_id, "user": username})

    async def _escalate(self, process: asyncio.subprocess.Process) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
            if process.returncode is not None:
                return
            with contextlib.suppress(ProcessLookupError):
                process.send_signal(sig)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), self._cancel_step_s)

    async def _update(
        self, run_id: int, *, status: RunStatus, started_at: bool = False
    ) -> datetime | None:
        async with self._sessionmaker() as db:
            run = await db.get(Run, run_id)
            if run is None:  # pragma: no cover - rows are never deleted while active
                return None
            run.status = status.value
            if started_at:
                run.started_at = utcnow()
            await db.commit()
            return run.started_at

    async def _finish(
        self,
        active: ActiveRun,
        status: RunStatus,
        error: str | None,
        summary: dict[str, object] | None = None,
    ) -> None:
        async with self._sessionmaker() as db:
            run = await db.get(Run, active.run_id)
            if run is not None:
                run.status = status.value
                run.error = error
                run.finished_at = utcnow()
                if summary is not None:
                    run.summary_json = json.dumps(summary)
                await db.commit()
        exit_code = summary.get("exit_code") if summary else None
        self._status(
            active, status, exit_code=exit_code if isinstance(exit_code, int) else None, error=error
        )
        self.hub.finish(active.run_id)
        self._active.pop(active.run_id, None)
        log.info(
            "run finished", extra={"run_id": active.run_id, "status": status.value, "error": error}
        )

    async def wait(self, run_id: int) -> None:
        """Wait for a run to finish (used by tests and shutdown)."""
        active = self._active.get(run_id)
        if active is not None and active.task is not None:
            await active.task

    async def shutdown(self) -> None:
        """Stop child processes when the agent stops; restart recovery marks them failed."""
        for active in list(self._active.values()):
            if active.process is not None and active.process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    active.process.terminate()
        tasks = [a.task for a in self._active.values() if a.task is not None]
        if tasks:
            await asyncio.wait(tasks, timeout=10)

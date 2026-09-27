"""RunManager: starts pgbench as a child process and tracks its lifecycle.

Stage 1 covers `pgbench -i` (kind=init); benchmark runs are added in stage 3.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import IO, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.command import InitOptions, build_init_argv
from app.core.connection import ConnParams
from app.core.parsers.progress import InitProgress, parse_init_phase, parse_init_progress
from app.storage.models import Run, RunKind, RunStatus, utcnow

log = logging.getLogger(__name__)

LOG_BUFFER_LINES = 2000
_LINE_SPLIT = re.compile(rb"\r\n|\r|\n")
RESTART_ERROR = "Агент перезапущен во время выполнения"

Stream = Literal["stdout", "stderr"]


class RunLimitError(Exception):
    """The agent already runs as many processes as max_parallel_runs allows."""


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


class RunManager:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        runs_dir: Path,
        max_parallel: int,
        pgbench_binary: str,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._runs_dir = runs_dir
        self._max_parallel = max_parallel
        self._binary = pgbench_binary
        self._active: dict[int, ActiveRun] = {}
        self._lock = asyncio.Lock()

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
        async with self._lock:
            if len(self._active) >= self._max_parallel:
                raise RunLimitError
            argv = build_init_argv(self._binary, options)
            config = {"kind": "init", "connection": public_params(params), "init": asdict(options)}
            async with self._sessionmaker() as db:
                run = Run(
                    profile_id=profile_id,
                    kind=RunKind.init.value,
                    status=RunStatus.queued.value,
                    started_by=started_by,
                    config_json=json.dumps(config, ensure_ascii=False),
                    argv_json=json.dumps(argv),
                    pgbench_version=pgbench_version,
                    server_version=server_version,
                )
                db.add(run)
                await db.commit()
                run_id = run.id
            active = ActiveRun(run_id=run_id, kind=RunKind.init)
            self._active[run_id] = active

        run_dir = self._runs_dir / str(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
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
        await self._update(run_id, status=RunStatus.running, started_at=True)
        active.task = asyncio.create_task(self._supervise(active, process, run_dir))
        log.info("run started", extra={"run_id": run_id, "kind": "init", "user": started_by})
        return run_id

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
        if code == 0:
            await self._finish(active, RunStatus.completed, None, {"exit_code": code})
        else:
            last = next((e.line for e in reversed(active.log) if e.stream == "stderr"), None)
            await self._finish(
                active,
                RunStatus.failed,
                last or f"pgbench завершился с кодом {code}",
                {"exit_code": code},
            )

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
        if active.kind is RunKind.init:
            progress = parse_init_progress(line)
            if progress is not None:
                active.init_progress = progress
            phase = parse_init_phase(line)
            if phase is not None:
                active.phase = phase

    async def _update(self, run_id: int, *, status: RunStatus, started_at: bool = False) -> None:
        async with self._sessionmaker() as db:
            run = await db.get(Run, run_id)
            if run is None:  # pragma: no cover - rows are never deleted while active
                return
            run.status = status.value
            if started_at:
                run.started_at = utcnow()
            await db.commit()

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

"""Runs: command preview, dry run, start, status, progress, report and files."""

from __future__ import annotations

import json
import logging
import re
from collections import deque
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import select

from app.api.deps import DbDep, EditorDep, SettingsDep, ViewerDep, client_ip
from app.api.errors import api_error
from app.api.profiles import (
    get_profile_or_404,
    profile_params,
    require_ready_agent,
    run_check,
)
from app.config import Settings
from app.core.command import build_bench_argv, build_dry_argv, render_command
from app.core.healthchecks import HealthService
from app.core.limits import agent_cpu_count
from app.core.plan import Plan, build_plan
from app.core.report import ReportOptions
from app.core.runner import (
    LogLine,
    ProgressPlan,
    RunLimitError,
    RunManager,
    RunNotActiveError,
    public_params,
    run_dry,
)
from app.schemas import (
    ActiveRunOut,
    CommandPreview,
    ConnectionTestFail,
    DryRunRequest,
    DryRunResult,
    ErrorResponse,
    HistogramBucketOut,
    InitProgressOut,
    LogLineOut,
    ReportOut,
    RunConfig,
    RunFileOut,
    RunOut,
    RunStarted,
    RunSummaryOut,
    SeriesPointOut,
    StatementOut,
)
from app.storage.models import Run, RunHistogram, RunSeries, RunStatement, RunStatus

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["runs"])

LOG_TAIL_LINES = 200
DRY_OUTPUT_LIMIT = 64 * 1024
RAW_OUTPUT_LIMIT = 256 * 1024
# Files of a run directory offered for download: logs, pgbench logs and scripts.
_FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_GZIP = "application/gzip"

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


def _pgbench_major(request: Request) -> int | None:
    health: HealthService = request.app.state.health
    version = health.pgbench_version
    return int(version.split(".")[0]) if version else None


def _plan(
    request: Request,
    settings: Settings,
    config: RunConfig,
    free_connections: int | None,
    server_major: int | None,
) -> Plan:
    return build_plan(
        config,
        settings.limits,
        progress_interval_s=settings.pgbench.default_progress_interval_s,
        free_connections=free_connections,
        cpu_count=agent_cpu_count(),
        server_major=server_major,
        pgbench_major=_pgbench_major(request),
    )


def _enforce(plan: Plan, confirmed: list[str]) -> None:
    """422 on any error finding or on a danger/warning finding that was not confirmed."""
    findings = [f.model_dump() for f in plan.findings]
    if plan.errors:
        raise api_error(
            422,
            "config_invalid",
            "Конфигурация нарушает лимиты или правила: "
            + "; ".join(e.message for e in plan.errors),
            findings=findings,
        )
    missing = plan.missing_confirmations(confirmed)
    if missing:
        raise api_error(
            422,
            "confirmation_required",
            "Нужно подтвердить предупреждения и опасные конструкции перед запуском",
            missing=missing,
            findings=findings,
        )


def _connection_failed(check: ConnectionTestFail) -> Exception:
    # Same structure as POST /api/profiles/test; pgbench is not started.
    return api_error(
        422,
        check.code,
        check.message,
        **check.model_dump(exclude={"code", "message"}, mode="json"),
    )


@router.post("/preview", response_model=CommandPreview, responses=_ERRORS)
async def preview(
    config: RunConfig, request: Request, db: DbDep, settings: SettingsDep, _user: EditorDep
) -> CommandPreview:
    """The exact argv that POST /api/runs would start, without connecting to the database."""
    profile = await get_profile_or_404(db, config.profile_id)
    params = profile_params(request, profile)
    plan = _plan(request, settings, config, free_connections=None, server_major=None)
    argv = build_bench_argv(settings.pgbench.binary, plan.options)
    env = params.libpq_env()
    return CommandPreview(
        argv=argv,
        env={k: ("••••••" if k == "PGPASSWORD" else v) for k, v in env.items()},
        command=render_command(argv, env),
        findings=plan.findings,
    )


@router.post(
    "/dry",
    response_model=DryRunResult,
    responses={**_ERRORS, 503: {"model": ErrorResponse}},
)
async def dry_run(
    body: DryRunRequest, request: Request, db: DbDep, settings: SettingsDep, user: EditorDep
) -> DryRunResult:
    """`pgbench -c 1 -t 1 -n` for one scenario: real queries, same rules as a run."""
    profile = await get_profile_or_404(db, body.profile_id)
    await require_ready_agent(request)
    params = profile_params(request, profile)
    check = await run_check(request, params)
    if isinstance(check, ConnectionTestFail):
        raise _connection_failed(check)

    config = RunConfig(
        profile_id=body.profile_id,
        mode="transactions",
        transactions=1,
        protocol=body.protocol,
        variables=body.variables,
        scenarios=[body.scenario],
    )
    plan = _plan(request, settings, config, None, check.server_major)
    # Only script rules apply to a dry run; its load (-c 1 -t 1) is fixed.
    plan = Plan(plan.options, plan.files, [f for f in plan.findings if f.scenario is not None])
    _enforce(plan, body.confirmed_rules)

    argv = build_dry_argv(settings.pgbench.binary, plan.options)
    result = await run_dry(argv, plan.files, params, settings.storage.runs_dir / ".dry")
    log.info(
        "dry run",
        extra={"ip": client_ip(request), "username": user.username, "exit_code": result.exit_code},
    )
    return DryRunResult(
        ok=result.exit_code == 0,
        exit_code=result.exit_code,
        duration_ms=round(result.duration_ms, 1),
        stdout=result.stdout[-DRY_OUTPUT_LIMIT:],
        stderr=result.stderr[-DRY_OUTPUT_LIMIT:],
        timed_out=result.timed_out,
    )


@router.post(
    "",
    response_model=RunStarted,
    status_code=202,
    responses={**_ERRORS, 409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def start_run(
    config: RunConfig, request: Request, db: DbDep, settings: SettingsDep, user: EditorDep
) -> RunStarted:
    """Every check of the form is repeated here; a bypassed UI gets 422, never a run."""
    profile = await get_profile_or_404(db, config.profile_id)
    await require_ready_agent(request)
    params = profile_params(request, profile)
    check = await run_check(request, params)
    if isinstance(check, ConnectionTestFail):
        raise _connection_failed(check)

    plan = _plan(request, settings, config, check.free_connections, check.server_major)
    _enforce(plan, config.confirmed_rules)

    argv = build_bench_argv(settings.pgbench.binary, plan.options)
    confirmed = plan.required_confirmations
    stored_config: dict[str, object] = {
        "kind": "bench",
        "connection": public_params(params),
        "profile_name": profile.name,
        "run_config": config.model_dump(mode="json", exclude={"confirmed_rules"}),
        "files": plan.files,
    }
    runs: RunManager = request.app.state.runs
    health: HealthService = request.app.state.health
    try:
        run_id = await runs.start_bench(
            profile_id=profile.id,
            params=params,
            argv=argv,
            files=plan.files,
            config=stored_config,
            confirmed_rules=confirmed,
            started_by=user.username,
            pgbench_version=health.pgbench_version,
            server_version=check.server_version,
            plan=ProgressPlan(
                mode=config.mode,
                duration_s=config.duration_s,
                clients=config.clients,
                transactions=config.transactions,
            ),
            summary={
                "profile_id": profile.id,
                "profile_name": profile.name,
                "dbname": profile.dbname,
                "mode": config.mode,
                "duration_s": config.duration_s,
                "transactions": config.transactions,
                "clients": config.clients,
                "threads": config.threads,
                "protocol": config.protocol,
                "rate_tps": config.rate_tps,
                "progress_interval_s": settings.pgbench.default_progress_interval_s,
                "scenarios": [
                    {"kind": s.kind, "name": s.name, "weight": s.weight} for s in config.scenarios
                ],
            },
            report=ReportOptions(
                detailed=config.detailed_log,
                with_lag=config.rate_tps is not None,
                sampling_rate=config.sampling_rate,
                progress_interval_s=settings.pgbench.default_progress_interval_s,
                scripts=[s.name for s in config.scenarios],
            ),
        )
    except RunLimitError as exc:
        raise api_error(
            409,
            "agent_busy",
            "На агенте уже выполняется запуск. Дождитесь его завершения.",
            active_runs=runs.active_ids,
        ) from exc
    log.info(
        "run requested",
        extra={
            "ip": client_ip(request),
            "username": user.username,
            "run_id": run_id,
            "confirmed_rules": confirmed,
        },
    )
    return RunStarted(run_id=run_id)


def _file_tail(path: Path, stream: str, limit: int) -> list[LogLineOut]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", errors="replace") as fh:
        lines = deque((line.rstrip("\n") for line in fh), maxlen=limit)
    return [LogLineOut(stream=stream, line=line) for line in lines if line]


@router.get("/active", response_model=ActiveRunOut, responses=_ERRORS)
async def active_run(request: Request, db: DbDep, _user: ViewerDep) -> ActiveRunOut:
    """The run in progress on this agent, for the «Выполнение · идёт» menu item."""
    runs: RunManager = request.app.state.runs
    for run_id in runs.active_ids:
        run = await db.get(Run, run_id)
        if run is not None:
            return ActiveRunOut(run_id=run.id, kind=run.kind, status=run.status)
    return ActiveRunOut(run_id=None, kind=None, status=None)


@router.post(
    "/{run_id}/cancel",
    status_code=202,
    response_model=RunStarted,
    responses={**_ERRORS, 409: {"model": ErrorResponse}},
)
async def cancel_run(run_id: int, request: Request, db: DbDep, user: EditorDep) -> RunStarted:
    """SIGINT, then SIGTERM after 5 s, then SIGKILL after 5 more; the status becomes cancelled."""
    if await db.get(Run, run_id) is None:
        raise api_error(404, "run_not_found", "Запуск не найден")
    runs: RunManager = request.app.state.runs
    try:
        await runs.cancel(run_id, user.username)
    except RunNotActiveError as exc:
        raise api_error(409, "run_not_active", "Запуск уже завершён") from exc
    log.info(
        "run cancel", extra={"ip": client_ip(request), "username": user.username, "run_id": run_id}
    )
    return RunStarted(run_id=run_id)


def _summary(run: Run) -> RunSummaryOut | None:
    if run.summary_json is None:
        return None
    try:
        return RunSummaryOut.model_validate_json(run.summary_json)
    except ValidationError:  # pragma: no cover - written by this code only
        log.warning("run summary unreadable", extra={"run_id": run.id})
        return None


def _run_out(run: Run, request: Request, settings: Settings) -> RunOut:
    manager: RunManager = request.app.state.runs
    active = manager.get_active(run.id)
    progress: InitProgressOut | None = None
    log_tail: list[LogLineOut]
    if active is not None:
        lines: list[LogLine] = list(active.log)[-LOG_TAIL_LINES:]
        log_tail = [LogLineOut(stream=entry.stream, line=entry.line) for entry in lines]
        p = active.init_progress
        progress = InitProgressOut(
            done=p.done if p else None,
            total=p.total if p else None,
            pct=p.pct if p else None,
            elapsed_s=p.elapsed_s if p else None,
            remaining_s=p.remaining_s if p else None,
            phase=active.phase,
        )
    else:
        run_dir = settings.storage.runs_dir / str(run.id)
        log_tail = _file_tail(run_dir / "stdout.log", "stdout", LOG_TAIL_LINES) + _file_tail(
            run_dir / "stderr.log", "stderr", LOG_TAIL_LINES
        )

    return RunOut(
        id=run.id,
        kind=run.kind,
        status=run.status,
        profile_id=run.profile_id,
        started_by=run.started_by,
        stopped_by=run.stopped_by,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        pgbench_version=run.pgbench_version,
        server_version=run.server_version,
        error=run.error,
        argv=json.loads(run.argv_json),
        config=json.loads(run.config_json),
        progress=progress,
        log_tail=log_tail,
        summary=_summary(run),
    )


async def _get_run_or_404(db: DbDep, run_id: int) -> Run:
    run = await db.get(Run, run_id)
    if run is None:
        raise api_error(404, "run_not_found", "Запуск не найден")
    return run


@router.get(
    "/{run_id}",
    response_model=RunOut,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_run(
    run_id: int, request: Request, db: DbDep, settings: SettingsDep, _user: ViewerDep
) -> RunOut:
    return _run_out(await _get_run_or_404(db, run_id), request, settings)


def run_files(run_dir: Path) -> list[RunFileOut]:
    """Regular files of the run directory (never links or subdirectories)."""
    if not run_dir.is_dir():
        return []
    files = [
        RunFileOut(name=p.name, size_bytes=p.stat().st_size)
        for p in run_dir.iterdir()
        if _FILE_NAME.match(p.name) and p.is_file() and not p.is_symlink()
    ]
    order = {"stdout.log": 0, "stderr.log": 1}
    return sorted(files, key=lambda f: (order.get(f.name, 2), f.name))


def _raw_output(path: Path) -> tuple[str, bool]:
    if not path.is_file():
        return "", False
    with path.open("rb") as fh:
        data = fh.read(RAW_OUTPUT_LIMIT + 1)
    return data[:RAW_OUTPUT_LIMIT].decode(errors="replace"), len(data) > RAW_OUTPUT_LIMIT


@router.get(
    "/{run_id}/report",
    response_model=ReportOut,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def get_report(
    run_id: int, request: Request, db: DbDep, settings: SettingsDep, _user: ViewerDep
) -> ReportOut:
    """Summary, per-second series, -r rows, histogram, raw output and files of a finished run."""
    run = await _get_run_or_404(db, run_id)
    if RunStatus(run.status).is_active:
        raise api_error(
            409, "run_active", "Запуск ещё выполняется: отчёт появится после завершения"
        )

    series = await db.execute(
        select(RunSeries).where(RunSeries.run_id == run_id).order_by(RunSeries.t_s)
    )
    statements = await db.execute(
        select(RunStatement).where(RunStatement.run_id == run_id).order_by(RunStatement.id)
    )
    histogram = await db.execute(
        select(RunHistogram)
        .where(RunHistogram.run_id == run_id)
        .order_by(RunHistogram.bucket_upper_ms)
    )
    run_dir = settings.storage.runs_dir / str(run_id)
    raw, truncated = _raw_output(run_dir / "stdout.log")
    return ReportOut(
        run=_run_out(run, request, settings),
        series=[SeriesPointOut.model_validate(p) for p in series.scalars()],
        statements=[StatementOut.model_validate(s) for s in statements.scalars()],
        histogram=[
            HistogramBucketOut(upper_ms=h.bucket_upper_ms, count=h.count)
            for h in histogram.scalars()
        ],
        raw_output=raw,
        raw_output_truncated=truncated,
        files=run_files(run_dir),
    )


@router.get(
    "/{run_id}/files/{name}",
    response_class=FileResponse,
    responses={
        200: {"content": {"text/plain": {}, _GZIP: {}}},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def get_run_file(
    run_id: int, name: str, db: DbDep, settings: SettingsDep, _user: ViewerDep
) -> FileResponse:
    """Download stdout, stderr, pgbench logs or scripts of a run; only its own directory."""
    await _get_run_or_404(db, run_id)
    run_dir = settings.storage.runs_dir / str(run_id)
    path = run_dir / name
    if (
        not _FILE_NAME.match(name)
        or path.parent != run_dir
        or path.is_symlink()
        or not path.is_file()
    ):
        raise api_error(404, "file_not_found", "Файл запуска не найден")
    return FileResponse(
        path,
        media_type=_GZIP if name.endswith(".gz") else "text/plain; charset=utf-8",
        filename=f"run-{run_id}-{name}",
    )

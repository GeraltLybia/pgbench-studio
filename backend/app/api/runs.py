"""Runs: status and progress. Stage 1 exposes a run's metadata for `pgbench -i`."""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path

from fastapi import APIRouter, Request

from app.api.deps import DbDep, SettingsDep, ViewerDep
from app.api.errors import api_error
from app.core.runner import LogLine, RunManager
from app.schemas import ErrorResponse, InitProgressOut, LogLineOut, RunOut
from app.storage.models import Run

router = APIRouter(prefix="/api/runs", tags=["runs"])

LOG_TAIL_LINES = 200


def _file_tail(path: Path, stream: str, limit: int) -> list[LogLineOut]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", errors="replace") as fh:
        lines = deque((line.rstrip("\n") for line in fh), maxlen=limit)
    return [LogLineOut(stream=stream, line=line) for line in lines if line]


@router.get(
    "/{run_id}",
    response_model=RunOut,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_run(
    run_id: int, request: Request, db: DbDep, settings: SettingsDep, _user: ViewerDep
) -> RunOut:
    run = await db.get(Run, run_id)
    if run is None:
        raise api_error(404, "run_not_found", "Запуск не найден")

    manager: RunManager = request.app.state.runs
    active = manager.get_active(run_id)
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
        run_dir = settings.storage.runs_dir / str(run_id)
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
    )

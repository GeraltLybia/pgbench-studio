"""Removing runs: one on request, and the daily purge of runs older than keep_runs_days."""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Callable, Collection
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.storage.models import Run, RunStatus, utcnow

log = logging.getLogger(__name__)

PURGE_INTERVAL_S = 24 * 3600


def remove_run_dir(runs_dir: Path, run_id: int) -> None:
    """The run's own directory only; never follows a link out of runs_dir."""
    path = runs_dir / str(run_id)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)


async def delete_runs(
    sessionmaker: async_sessionmaker[AsyncSession], runs_dir: Path, ids: Collection[int]
) -> None:
    """Rows of the runs (series, statements, histogram, resources cascade) and their files."""
    if not ids:
        return
    async with sessionmaker() as db:
        await db.execute(delete(Run).where(Run.id.in_(list(ids))))
        await db.commit()
    for run_id in ids:
        await asyncio.to_thread(remove_run_dir, runs_dir, run_id)


async def purge_old_runs(
    sessionmaker: async_sessionmaker[AsyncSession],
    runs_dir: Path,
    keep_days: int,
    active: Collection[int],
    now: datetime | None = None,
) -> list[int]:
    cutoff = (now or utcnow()) - timedelta(days=keep_days)
    finished = [s.value for s in RunStatus if not s.is_active]
    async with sessionmaker() as db:
        result = await db.execute(
            select(Run.id).where(Run.created_at < cutoff, Run.status.in_(finished))
        )
        ids = [int(i) for i in result.scalars() if i not in active]
    await delete_runs(sessionmaker, runs_dir, ids)
    if ids:
        log.info("old runs purged", extra={"runs": ids, "keep_days": keep_days})
    return ids


async def purge_loop(
    sessionmaker: async_sessionmaker[AsyncSession],
    runs_dir: Path,
    keep_days: int,
    active: Callable[[], Collection[int]],
    interval_s: float = PURGE_INTERVAL_S,
) -> None:
    """Once at startup and then once a day; a failed pass is logged and retried next time."""
    while True:
        try:
            await purge_old_runs(sessionmaker, runs_dir, keep_days, active())
        except Exception:  # pragma: no cover - logged, the loop keeps going
            log.exception("run purge failed")
        await asyncio.sleep(interval_s)

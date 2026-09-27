from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.config import Settings
from app.core.command import InitOptions
from app.core.connection import ConnParams
from app.core.runner import RESTART_ERROR, RunLimitError, RunManager, child_env
from app.storage.db import create_engine_for, make_sessionmaker, run_migrations
from app.storage.models import Profile, Run, RunKind, RunStatus

OPTIONS = InitOptions(scale=1, fillfactor=100, foreign_keys=True, unlogged=False)


def params(dbname: str = "bench") -> ConnParams:
    return ConnParams(
        host="db",
        port=5432,
        dbname=dbname,
        user="u",
        sslmode="prefer",
        app_name="pgbench-studio",
        connect_timeout_s=5,
        password="top-secret",
    )


@pytest.fixture
async def manager(settings: Settings):  # type: ignore[no-untyped-def]
    engine = await with_profile(settings)
    runs = RunManager(
        make_sessionmaker(engine), settings.storage.runs_dir, 1, settings.pgbench.binary
    )
    yield runs
    await runs.shutdown()
    await engine.dispose()


async def with_profile(settings: Settings):  # type: ignore[no-untyped-def]
    run_migrations(settings.storage.sqlite_path)
    engine = create_engine_for(settings.storage.sqlite_path)
    async with make_sessionmaker(engine)() as db:
        db.add(
            Profile(
                id=1,
                name="p",
                host="db",
                port=5432,
                dbname="bench",
                user="u",
                sslmode="prefer",
                app_name="a",
                connect_timeout_s=5,
            )
        )
        await db.commit()
    return engine


async def load(manager: RunManager, run_id: int) -> Run:
    async with manager._sessionmaker() as db:
        run = await db.get(Run, run_id)
        assert run is not None
        return run


async def start(manager: RunManager, dbname: str = "bench") -> int:
    return await manager.start_init(
        profile_id=1,
        params=params(dbname),
        options=OPTIONS,
        started_by="ed",
        pgbench_version="18.1",
        server_version="18.0",
    )


async def test_successful_init(manager: RunManager, settings: Settings) -> None:
    run_id = await start(manager)
    active = manager.get_active(run_id)
    assert active is not None
    await manager.wait(run_id)

    run = await load(manager, run_id)
    assert run.status == RunStatus.completed
    assert run.kind == RunKind.init
    assert run.started_by == "ed"
    assert run.started_at is not None and run.finished_at is not None
    assert json.loads(run.summary_json or "{}") == {"exit_code": 0}
    config = json.loads(run.config_json)
    assert config["init"]["scale"] == 1
    assert "password" not in config["connection"]
    assert "top-secret" not in run.config_json + run.argv_json

    assert active.init_progress is not None and active.init_progress.pct == 100.0
    assert active.phase == "Готово"
    assert manager.get_active(run_id) is None

    run_dir = settings.storage.runs_dir / str(run_id)
    stderr = (run_dir / "stderr.log").read_text()
    assert "50000 of 100000 tuples" in stderr  # \r-terminated progress line was split
    assert "creating primary keys..." in stderr
    argv = (run_dir / "argv.txt").read_text()
    assert "top-secret" not in argv
    assert "-i -s 1 -F 100 --foreign-keys" in argv
    env = (run_dir / "env.txt").read_text()
    assert "PGPASSWORD=top-secret" in env
    assert "PGB_STUDIO_SECRET_KEY" not in env
    assert "LC_ALL=C" in env


async def test_failed_init_keeps_last_error(manager: RunManager) -> None:
    run_id = await start(manager, "failme")
    await manager.wait(run_id)
    run = await load(manager, run_id)
    assert run.status == RunStatus.failed
    assert run.error is not None and "boom" in run.error
    assert json.loads(run.summary_json or "{}") == {"exit_code": 1}


async def test_one_run_at_a_time(manager: RunManager) -> None:
    run_id = await start(manager, "slow")
    with pytest.raises(RunLimitError):
        await start(manager)
    assert manager.active_ids == [run_id]
    await manager.shutdown()
    run = await load(manager, run_id)
    assert run.status == RunStatus.failed


async def test_missing_binary(settings: Settings, tmp_path: Path) -> None:
    engine = await with_profile(settings)
    runs = RunManager(make_sessionmaker(engine), tmp_path / "runs", 1, str(tmp_path / "nope"))
    run_id = await start(runs)
    run = await load(runs, run_id)
    assert run.status == RunStatus.failed
    assert run.error is not None and "Не удалось запустить pgbench" in run.error
    assert runs.active_ids == []
    await engine.dispose()


async def test_recover_marks_active_runs_failed(manager: RunManager) -> None:
    async with manager._sessionmaker() as db:
        for status in (RunStatus.running, RunStatus.queued, RunStatus.completed):
            db.add(Run(kind="init", status=status.value, config_json="{}", argv_json="[]"))
        await db.commit()
    assert await manager.recover() == 2
    async with manager._sessionmaker() as db:
        from sqlalchemy import select

        runs = list((await db.execute(select(Run).order_by(Run.id))).scalars())
    assert [r.status for r in runs] == ["failed", "failed", "completed"]
    assert runs[0].error == RESTART_ERROR
    assert await manager.recover() == 0


def test_child_env_is_minimal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGB_STUDIO_SECRET_KEY", "x")
    env = child_env(params(), tmp_path)
    assert set(env) == {
        "PATH",
        "LC_ALL",
        "HOME",
        "PGHOST",
        "PGPORT",
        "PGDATABASE",
        "PGUSER",
        "PGSSLMODE",
        "PGAPPNAME",
        "PGCONNECT_TIMEOUT",
        "PGPASSWORD",
    }
    assert env["HOME"] == str(tmp_path)


async def test_wait_for_unknown_run_is_noop(manager: RunManager) -> None:
    await asyncio.wait_for(manager.wait(12345), 1)

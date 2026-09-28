from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.config import LimitsSettings
from app.core.command import InitOptions, build_bench_argv, build_dry_argv
from app.core.connection import ConnFailure, ServerFacts, check_connection
from app.core.plan import Plan, build_plan
from app.core.runner import ProgressPlan, RunManager, child_env, run_dry
from app.core.validator import validate_script
from app.schemas import RunConfig
from app.storage.db import create_engine_for, make_sessionmaker, run_migrations
from app.storage.models import Profile, Run, RunStatus
from tests.integration.conftest import Server

pytestmark = pytest.mark.integration


async def test_connection_facts(server: Server) -> None:
    facts = await check_connection(server.params())
    assert isinstance(facts, ServerFacts), facts
    assert facts.server_major == server.major
    assert facts.max_connections >= 20
    assert 0 < facts.free_connections < facts.max_connections


@pytest.fixture
async def runs(tmp_path: Path, pgbench: str) -> AsyncIterator[RunManager]:
    db_path = tmp_path / "studio.db"
    run_migrations(db_path)
    engine = create_engine_for(db_path)
    sessionmaker = make_sessionmaker(engine)
    async with sessionmaker() as db:
        db.add(
            Profile(
                id=1,
                name="it",
                host="h",
                port=1,
                dbname="bench",
                user="bench",
                sslmode="prefer",
                app_name="it",
                connect_timeout_s=5,
            )
        )
        await db.commit()
    manager = RunManager(sessionmaker, tmp_path / "runs", 1, pgbench)
    yield manager
    await manager.shutdown()
    await engine.dispose()


async def test_init_then_benchmark(
    server: Server, runs: RunManager, pgbench: str, tmp_path: Path
) -> None:
    params = server.params()
    run_id = await runs.start_init(
        profile_id=1,
        params=params,
        options=InitOptions(scale=2, fillfactor=90, foreign_keys=True, unlogged=False),
        started_by="it",
        pgbench_version="18",
        server_version=str(server.major),
    )
    active = runs.get_active(run_id)
    assert active is not None
    await asyncio.wait_for(runs.wait(run_id), 120)

    async with runs._sessionmaker() as db:
        run = await db.get(Run, run_id)
        assert run is not None
        assert run.status == RunStatus.completed, run.error
    # Real pgbench 18 output is understood by the parsers.
    assert active.init_progress is not None
    assert active.init_progress.total == 200_000
    assert active.init_progress.pct == 100.0
    assert active.phase == "Готово"

    facts = await check_connection(params)
    assert isinstance(facts, ServerFacts)
    assert facts.pgbench_tables
    assert facts.scale == 2
    assert facts.accounts_rows is not None and facts.accounts_rows > 0

    # pgbench 18 runs a short test against this server version.
    work = tmp_path / "bench"
    work.mkdir()
    proc = await asyncio.create_subprocess_exec(
        pgbench,
        "-c",
        "2",
        "-j",
        "2",
        "-T",
        "3",
        "-P",
        "1",
        "-r",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=child_env(params, work),
        cwd=work,
    )
    out, err = await asyncio.wait_for(proc.communicate(), 60)
    assert proc.returncode == 0, err.decode()
    assert "tps = " in out.decode()
    assert "progress: " in err.decode()


async def test_auth_failed(server: Server) -> None:
    result = await check_connection(server.params(password="wrong"))
    assert isinstance(result, ConnFailure) and result.code == "auth_failed", result


async def test_database_not_found(server: Server) -> None:
    result = await check_connection(server.params(dbname="missing_db"))
    assert isinstance(result, ConnFailure) and result.code == "database_not_found", result


async def test_no_connect_privilege(server: Server) -> None:
    server.psql(
        "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'noconnect') THEN "
        "CREATE ROLE noconnect LOGIN PASSWORD 'x'; END IF; END $$;"
    )
    server.psql("CREATE DATABASE locked")
    server.psql("REVOKE CONNECT ON DATABASE locked FROM PUBLIC")
    try:
        result = await check_connection(
            server.params(dbname="locked", user="noconnect", password="x")
        )
        assert isinstance(result, ConnFailure) and result.code == "no_connect_privilege", result
    finally:
        server.psql("DROP DATABASE locked")


async def test_ssl_error(server: Server) -> None:
    # The official image runs without SSL, so a required SSL connection fails.
    result = await check_connection(server.params(sslmode="require"))
    assert isinstance(result, ConnFailure) and result.code == "ssl_error", result


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


async def test_connection_refused(server: Server) -> None:
    result = await check_connection(server.params(host="127.0.0.1", port=free_port()))
    assert isinstance(result, ConnFailure) and result.code == "connection_refused", result


async def test_host_unreachable(server: Server) -> None:
    result = await check_connection(server.params(host="no-such-host.invalid"))
    assert isinstance(result, ConnFailure) and result.code == "host_unreachable", result


async def test_timeout(server: Server) -> None:
    # A listener that accepts TCP but never answers the PostgreSQL handshake.
    writers: list[asyncio.StreamWriter] = []

    async def silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writers.append(writer)
        await reader.read()  # until the client gives up and disconnects

    listener = await asyncio.start_server(silent, "127.0.0.1", 0)
    port = listener.sockets[0].getsockname()[1]
    try:
        result = await check_connection(
            server.params(host="127.0.0.1", port=port, connect_timeout_s=2, sslmode="disable")
        )
    finally:
        for writer in writers:
            writer.close()
        listener.close()
    assert isinstance(result, ConnFailure) and result.code == "timeout", result


# --- stage 2: argv from the plan and dry runs against real servers ------------------------

HOT = (
    "\\set aid random(1, 100000 * :scale)\n"
    "SELECT abalance FROM pgbench_accounts WHERE aid = :aid;\n"
)


def _plan(**overrides: object) -> Plan:
    cfg: dict[str, object] = {
        "profile_id": 1,
        "mode": "duration",
        "duration_s": 10,
        "clients": 2,
        "threads": 1,
        "protocol": "prepared",
        "variables": [{"name": "delta", "value": "5"}],
        "scenarios": [
            {"kind": "builtin", "name": "select-only", "weight": 1},
            {"kind": "script", "name": "hot.sql", "body": HOT, "weight": 3},
        ],
    }
    cfg.update(overrides)
    return build_plan(
        RunConfig.model_validate(cfg),
        LimitsSettings(),
        progress_interval_s=1,
        free_connections=None,
        cpu_count=8,
        server_major=None,
        pgbench_major=18,
    )


async def _init(server: Server, runs: RunManager) -> None:
    run_id = await runs.start_init(
        profile_id=1,
        params=server.params(),
        options=InitOptions(scale=1, fillfactor=100, foreign_keys=False, unlogged=False),
        started_by="it",
        pgbench_version="18",
        server_version=None,
    )
    await asyncio.wait_for(runs.wait(run_id), 120)


async def test_dry_run_and_bench_with_scripts(
    server: Server, runs: RunManager, pgbench: str, tmp_path: Path
) -> None:
    await _init(server, runs)
    plan = _plan()
    assert plan.errors == []

    dry = await run_dry(
        build_dry_argv(pgbench, plan.options), plan.files, server.params(), tmp_path
    )
    assert dry.exit_code == 0, dry.stderr
    assert "actually processed: 1/1" in dry.stdout

    bench_plan = _plan(mode="transactions", transactions=20, duration_s=None)
    run_id = await runs.start_bench(
        profile_id=1,
        params=server.params(),
        argv=build_bench_argv(pgbench, bench_plan.options),
        files=bench_plan.files,
        config={},
        confirmed_rules=[],
        started_by="it",
        pgbench_version="18",
        server_version=None,
    )
    await asyncio.wait_for(runs.wait(run_id), 120)
    async with runs._sessionmaker() as db:
        run = await db.get(Run, run_id)
        assert run is not None and run.status == RunStatus.completed, run.error if run else None
    run_dir = runs._runs_dir / str(run_id)
    assert (
        "number of transactions actually processed: 40/40" in (run_dir / "stdout.log").read_text()
    )
    assert any(p.name.startswith("pgbench_log") for p in run_dir.iterdir())


async def test_dry_run_catches_what_the_validator_leaves_to_the_server(
    server: Server, pgbench: str, tmp_path: Path
) -> None:
    plan = _plan(
        scenarios=[{"kind": "script", "name": "t.sql", "body": "SELECT * FROM missing_table;"}]
    )
    assert plan.errors == []  # syntactically fine
    dry = await run_dry(
        build_dry_argv(pgbench, plan.options), plan.files, server.params(), tmp_path
    )
    assert dry.exit_code != 0
    assert "missing_table" in dry.stderr


async def test_version_rule_matches_the_server(server: Server) -> None:
    merge = (
        "MERGE INTO pgbench_accounts a USING pgbench_branches b ON a.bid = b.bid "
        "WHEN MATCHED THEN DO NOTHING;"
    )
    diagnostics = validate_script(merge, server.major).diagnostics
    has_version_error = any(d.rule == "server_version" for d in diagnostics)
    assert has_version_error is (server.major < 15)


# --- stage 3: live progress and cancel with real pgbench ----------------------------------


async def test_live_progress_and_cancel(server: Server, runs: RunManager, pgbench: str) -> None:
    await _init(server, runs)
    plan = _plan(duration_s=60)
    run_id = await runs.start_bench(
        profile_id=1,
        params=server.params(),
        argv=build_bench_argv(pgbench, plan.options),
        files=plan.files,
        config={},
        confirmed_rules=[],
        started_by="it",
        pgbench_version="18",
        server_version=None,
        plan=ProgressPlan(mode="duration", duration_s=60, clients=2),
    )
    events = runs.hub.get(run_id)
    assert events is not None
    for _ in range(100):
        if len(events.progress) >= 3:
            break
        await asyncio.sleep(0.1)
    points = events.progress
    assert len(points) >= 3, [m["line"] for m in events.log]
    assert points[0]["t"] == 1.0 and points[1]["t"] == 2.0
    assert all(p["tps"] > 0 for p in points)
    assert points[2]["pct"] == pytest.approx(5.0) and points[2]["eta_s"] == 57.0
    assert events.resources, "agent samples arrive every second"

    started = asyncio.get_running_loop().time()
    await runs.cancel(run_id, "it")
    await asyncio.wait_for(runs.wait(run_id), 15)
    assert asyncio.get_running_loop().time() - started < 10
    async with runs._sessionmaker() as db:
        run = await db.get(Run, run_id)
        assert run is not None
        assert (run.status, run.stopped_by) == (RunStatus.cancelled, "it")

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.core.command import InitOptions
from app.core.connection import ConnFailure, ServerFacts, check_connection
from app.core.runner import RunManager, child_env
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

from __future__ import annotations

import asyncio
from typing import Any

import psycopg
import pytest

from app.core import connection as conn_mod
from app.core.connection import (
    FAILURES,
    ConnFailure,
    ConnParams,
    ServerFacts,
    check_connection,
    classify_error,
    compatibility_warnings,
)

PARAMS = ConnParams(
    host="db.internal",
    port=5432,
    dbname="bench",
    user="bench_runner",
    sslmode="require",
    app_name="pgbench-studio",
    connect_timeout_s=3,
    password="s3cret",
)


def test_libpq_env_carries_password_only_when_set() -> None:
    env = PARAMS.libpq_env()
    assert env == {
        "PGHOST": "db.internal",
        "PGPORT": "5432",
        "PGDATABASE": "bench",
        "PGUSER": "bench_runner",
        "PGSSLMODE": "require",
        "PGAPPNAME": "pgbench-studio",
        "PGCONNECT_TIMEOUT": "3",
        "PGPASSWORD": "s3cret",
    }
    no_password = ConnParams(**{**PARAMS.__dict__, "password": None})
    assert "PGPASSWORD" not in no_password.libpq_env()
    assert "s3cret" not in repr(PARAMS)


@pytest.mark.parametrize(
    ("sqlstate", "raw", "code"),
    [
        ("28P01", 'FATAL:  password authentication failed for user "x"', "auth_failed"),
        ("28000", 'FATAL:  no pg_hba.conf entry for host "10.0.0.5"', "auth_failed"),
        ("3D000", 'FATAL:  database "nope" does not exist', "database_not_found"),
        ("42501", 'FATAL:  permission denied for database "bench"', "no_connect_privilege"),
        (
            None,
            'connection failed: could not translate host name "nohost" to address: '
            "nodename nor servname provided, or not known",
            "host_unreachable",
        ),
        (None, "connection failed: No route to host", "host_unreachable"),
        (None, "connection failed: Network is unreachable", "host_unreachable"),
        (
            None,
            'connection to server at "10.1.1.1", port 5432 failed: timeout expired',
            "timeout",
        ),
        (
            None,
            'connection to server at "127.0.0.1", port 1 failed: Connection refused\n'
            "\tIs the server running on that host and accepting TCP/IP connections?",
            "connection_refused",
        ),
        (None, "server does not support SSL, but SSL was required", "ssl_error"),
        (None, 'root certificate file "/x/root.crt" does not exist', "ssl_error"),
        (None, "fe_sendauth: no password supplied", "auth_failed"),
        (None, 'FATAL:  database "nope" does not exist', "database_not_found"),
        (None, 'FATAL:  permission denied for database "bench"', "no_connect_privilege"),
        (None, "something odd happened", "unknown"),
    ],
)
def test_classify_error(sqlstate: str | None, raw: str, code: str) -> None:
    result = classify_error(sqlstate, raw)
    assert result.code == code
    assert (result.message, result.hint) == FAILURES[code]
    assert result.raw == raw.strip()


def test_every_documented_code_has_texts() -> None:
    assert set(FAILURES) == {
        "host_unreachable",
        "timeout",
        "connection_refused",
        "auth_failed",
        "database_not_found",
        "no_connect_privilege",
        "ssl_error",
        "unknown",
    }


def test_compatibility_warnings() -> None:
    assert compatibility_warnings(16, 18) == []
    assert compatibility_warnings(18, 18) == []
    assert "новее" in compatibility_warnings(19, 18)[0]
    assert "старше" in compatibility_warnings(12, 18)[0]
    assert compatibility_warnings(19, None) == []


class FakeCursor:
    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.queries: list[str] = []
        self._row: Any = None

    async def __aenter__(self) -> FakeCursor:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, query: str, params: Any = None) -> None:
        self.queries.append(query)
        for needle, value in self.answers.items():
            if needle in query:
                if isinstance(value, Exception):
                    raise value
                self._row = (value,)
                return
        raise AssertionError(f"unexpected query: {query}")

    async def fetchone(self) -> Any:
        return self._row


class FakeConn:
    def __init__(self, answers: dict[str, Any]) -> None:
        self.cur = FakeCursor(answers)
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cur

    async def close(self) -> None:
        self.closed = True


BASE_ANSWERS: dict[str, Any] = {
    "SELECT 1": 1,
    "SHOW server_version": "16.4 (Debian 16.4-1.pgdg120+1)",
    "server_version_num": 160004,
    "max_connections": 200,
    "superuser_reserved_connections": 3,
    "pg_stat_activity": 13,
    "to_regclass": True,
    "pgbench_branches": 100,
    "reltuples": 9_998_000,
}


def connector(conn: FakeConn) -> Any:
    async def connect(_params: ConnParams) -> FakeConn:
        return conn

    return connect


async def test_check_collects_facts() -> None:
    conn = FakeConn(BASE_ANSWERS)
    facts = await check_connection(PARAMS, connector(conn))
    assert isinstance(facts, ServerFacts)
    assert facts.server_version.startswith("16.4")
    assert facts.server_major == 16
    assert facts.max_connections == 200
    assert facts.free_connections == 184
    assert facts.pgbench_tables
    assert facts.scale == 100
    assert facts.accounts_rows == 9_998_000
    assert facts.response_ms >= 0
    assert conn.closed


async def test_check_without_pgbench_tables_and_unanalyzed_accounts() -> None:
    facts = await check_connection(
        PARAMS, connector(FakeConn({**BASE_ANSWERS, "to_regclass": False}))
    )
    assert isinstance(facts, ServerFacts)
    assert (facts.pgbench_tables, facts.scale, facts.accounts_rows) == (False, None, None)

    facts = await check_connection(PARAMS, connector(FakeConn({**BASE_ANSWERS, "reltuples": -1})))
    assert isinstance(facts, ServerFacts)
    assert facts.accounts_rows == 100 * 100_000


async def test_free_connections_never_negative() -> None:
    facts = await check_connection(
        PARAMS, connector(FakeConn({**BASE_ANSWERS, "pg_stat_activity": 500}))
    )
    assert isinstance(facts, ServerFacts)
    assert facts.free_connections == 0


async def test_connect_error_is_classified() -> None:
    async def connect(_params: ConnParams) -> Any:
        raise psycopg.OperationalError("connection failed: Connection refused")

    result = await check_connection(PARAMS, connect)
    assert isinstance(result, ConnFailure)
    assert result.code == "connection_refused"


async def test_query_error_is_classified_and_connection_closed() -> None:
    conn = FakeConn({**BASE_ANSWERS, "max_connections": psycopg.OperationalError("lost")})
    result = await check_connection(PARAMS, connector(conn))
    assert isinstance(result, ConnFailure)
    assert result.code == "unknown"
    assert conn.closed


async def test_overall_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def hang(_params: ConnParams) -> Any:
        await asyncio.sleep(10)

    params = ConnParams(**{**PARAMS.__dict__, "connect_timeout_s": 1})
    monkeypatch.setattr(conn_mod, "CONNECT_SLACK_S", -0.95)
    result = await check_connection(params, hang)
    assert isinstance(result, ConnFailure)
    assert result.code == "timeout"


async def test_psycopg_connect_passes_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_connect(**kwargs: Any) -> str:
        seen.update(kwargs)
        return "conn"

    monkeypatch.setattr(conn_mod.psycopg.AsyncConnection, "connect", fake_connect)
    assert await conn_mod.psycopg_connect(PARAMS) == "conn"
    assert seen["password"] == "s3cret"
    assert seen["application_name"] == "pgbench-studio"
    assert seen["connect_timeout"] == 3
    seen.clear()
    await conn_mod.psycopg_connect(ConnParams(**{**PARAMS.__dict__, "password": None}))
    assert "password" not in seen

"""Connection check with psycopg: server facts for the UI and classified errors."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import psycopg

MIN_SERVER_MAJOR = 13
PGBENCH_TABLES = ("pgbench_accounts", "pgbench_branches", "pgbench_tellers", "pgbench_history")
ACCOUNTS_PER_SCALE = 100_000
# Extra time over connect_timeout before the whole attempt is abandoned.
CONNECT_SLACK_S = 5.0

SslMode = Literal["disable", "prefer", "require", "verify-full"]


@dataclass(frozen=True)
class ConnParams:
    host: str
    port: int
    dbname: str
    user: str
    sslmode: SslMode
    app_name: str
    connect_timeout_s: int
    password: str | None = field(default=None, repr=False)

    def libpq_env(self) -> dict[str, str]:
        """Environment for a pgbench child process. The password goes only here."""
        env = {
            "PGHOST": self.host,
            "PGPORT": str(self.port),
            "PGDATABASE": self.dbname,
            "PGUSER": self.user,
            "PGSSLMODE": self.sslmode,
            "PGAPPNAME": self.app_name,
            "PGCONNECT_TIMEOUT": str(self.connect_timeout_s),
        }
        if self.password is not None:
            env["PGPASSWORD"] = self.password
        return env


@dataclass(frozen=True)
class ServerFacts:
    server_version: str
    server_version_num: int
    response_ms: float
    max_connections: int
    reserved_connections: int
    used_connections: int
    pgbench_tables: bool
    scale: int | None
    accounts_rows: int | None

    @property
    def server_major(self) -> int:
        return self.server_version_num // 10_000

    @property
    def free_connections(self) -> int:
        return max(self.max_connections - self.reserved_connections - self.used_connections, 0)


@dataclass(frozen=True)
class ConnFailure:
    code: str
    message: str
    hint: str
    raw: str


FAILURES: dict[str, tuple[str, str]] = {
    "host_unreachable": (
        "Хост не найден или не отвечает",
        "Проверьте адрес хоста и сетевой доступ от агента нагрузки до сервера.",
    ),
    "timeout": (
        "Превышен таймаут подключения",
        "Проверьте доступность сервера или увеличьте таймаут подключения.",
    ),
    "connection_refused": (
        "Порт закрыт",
        "Проверьте порт и что PostgreSQL слушает этот адрес.",
    ),
    "auth_failed": (
        "Неверный пользователь или пароль",
        "Проверьте логин и пароль, а также правила pg_hba.conf для адреса агента нагрузки.",
    ),
    "database_not_found": (
        "База данных не существует",
        "Проверьте имя базы.",
    ),
    "no_connect_privilege": (
        "Нет права на подключение к базе",
        "Выдайте пользователю право CONNECT на базу.",
    ),
    "ssl_error": (
        "Ошибка SSL",
        "Смените SSL mode или проверьте сертификат сервера.",
    ),
    "unknown": (
        "Не удалось подключиться",
        "Посмотрите исходный текст ошибки PostgreSQL.",
    ),
}

_SQLSTATE_CODES = {
    "28P01": "auth_failed",  # invalid_password
    "28000": "auth_failed",  # invalid_authorization_specification, incl. pg_hba rejects
    "3D000": "database_not_found",
    "42501": "no_connect_privilege",
}

# libpq reports network-level failures without SQLSTATE; order matters.
_MESSAGE_CODES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("timeout", ("timeout expired", "timed out")),
    ("connection_refused", ("connection refused",)),
    (
        "host_unreachable",
        (
            "could not translate host name",
            "name or service not known",
            "nodename nor servname",
            "no address associated",
            "temporary failure in name resolution",
            "no route to host",
            "network is unreachable",
            "host is down",
            "host is unreachable",
        ),
    ),
    (
        "ssl_error",
        ("ssl", "certificate", "tls"),
    ),
    (
        "auth_failed",
        ("password authentication failed", "no password supplied", "pg_hba.conf"),
    ),
    ("database_not_found", ("does not exist",)),
    ("no_connect_privilege", ("permission denied for database",)),
)


def failure(code: str, raw: str) -> ConnFailure:
    message, hint = FAILURES[code]
    return ConnFailure(code=code, message=message, hint=hint, raw=raw.strip())


def classify_error(sqlstate: str | None, raw: str) -> ConnFailure:
    code = _SQLSTATE_CODES.get(sqlstate or "")
    if code is None:
        text = raw.lower()
        code = next(
            (c for c, needles in _MESSAGE_CODES if any(n in text for n in needles)), "unknown"
        )
    return failure(code, raw)


class Cursor(Protocol):
    async def execute(self, query: Any, params: Any = None) -> Any: ...
    async def fetchone(self) -> Any: ...


class Connection(Protocol):
    def cursor(self) -> Any: ...
    async def close(self) -> None: ...


Connector = Callable[[ConnParams], Awaitable[Connection]]


async def psycopg_connect(params: ConnParams) -> Connection:
    kwargs: dict[str, Any] = {
        "host": params.host,
        "port": params.port,
        "dbname": params.dbname,
        "user": params.user,
        "sslmode": params.sslmode,
        "application_name": params.app_name,
        "connect_timeout": params.connect_timeout_s,
        "autocommit": True,
    }
    if params.password is not None:
        kwargs["password"] = params.password
    conn: Connection = await psycopg.AsyncConnection.connect(**kwargs)
    return conn


async def _one(cur: Cursor, query: str, params: Mapping[str, Any] | None = None) -> Any:
    await cur.execute(query, params)
    row = await cur.fetchone()
    return row[0] if row is not None else None


async def collect_facts(conn: Connection) -> ServerFacts:
    async with conn.cursor() as cur:
        started = time.perf_counter()
        await _one(cur, "SELECT 1")
        response_ms = (time.perf_counter() - started) * 1000

        server_version = str(await _one(cur, "SHOW server_version"))
        version_num = int(await _one(cur, "SELECT current_setting('server_version_num')::int"))
        max_connections = int(await _one(cur, "SELECT current_setting('max_connections')::int"))
        # reserved_connections exists since PostgreSQL 16; missing_ok returns NULL before that.
        reserved = int(
            await _one(
                cur,
                "SELECT current_setting('superuser_reserved_connections')::int"
                " + coalesce(current_setting('reserved_connections', true)::int, 0)",
            )
        )
        used = int(
            await _one(
                cur,
                "SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend'",
            )
        )
        found = bool(
            await _one(
                cur,
                "SELECT bool_and(to_regclass(t) IS NOT NULL) FROM unnest(%(tables)s::text[]) t",
                {"tables": list(PGBENCH_TABLES)},
            )
        )
        scale: int | None = None
        accounts: int | None = None
        if found:
            scale = int(await _one(cur, "SELECT count(*) FROM pgbench_branches"))
            estimate = await _one(
                cur,
                "SELECT reltuples::bigint FROM pg_class WHERE oid = 'pgbench_accounts'::regclass",
            )
            # reltuples is -1 (or 0) until the table is analyzed; fall back to the scale.
            accounts = int(estimate) if estimate and estimate > 0 else scale * ACCOUNTS_PER_SCALE

    return ServerFacts(
        server_version=server_version,
        server_version_num=version_num,
        response_ms=round(response_ms, 2),
        max_connections=max_connections,
        reserved_connections=reserved,
        used_connections=used,
        pgbench_tables=found,
        scale=scale,
        accounts_rows=accounts,
    )


def compatibility_warnings(server_major: int, pgbench_major: int | None) -> list[str]:
    warnings: list[str] = []
    if server_major < MIN_SERVER_MAJOR:
        warnings.append(
            f"PostgreSQL {server_major} старше поддерживаемых версий 13–18: "
            "результаты не гарантируются."
        )
    if pgbench_major is not None and server_major > pgbench_major:
        warnings.append(
            f"Сервер PostgreSQL {server_major} новее pgbench {pgbench_major} на агенте."
        )
    return warnings


async def check_connection(
    params: ConnParams, connect: Connector = psycopg_connect
) -> ServerFacts | ConnFailure:
    """Connect, collect facts, never raise for connection problems."""
    try:
        # libpq enforces connect_timeout per address; this caps the whole attempt.
        conn = await asyncio.wait_for(connect(params), params.connect_timeout_s + CONNECT_SLACK_S)
    except TimeoutError:
        return failure("timeout", f"timeout expired after {params.connect_timeout_s} s")
    except psycopg.Error as exc:
        return classify_error(exc.sqlstate, str(exc))
    try:
        return await collect_facts(conn)
    except psycopg.Error as exc:
        return classify_error(exc.sqlstate, str(exc))
    finally:
        await conn.close()

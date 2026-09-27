"""Integration fixtures: real pgbench 18 against PostgreSQL 13 and 18 in Testcontainers.

Run with `uv run pytest -m integration`. Needs Docker and pgbench 18: set PGBENCH_BINARY or
put a pgbench 18 first in PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.core.connection import ConnParams

SERVER_VERSIONS = ["13", "18"]
PASSWORD = "bench-pass"


def pgbench_binary() -> str:
    candidates = [
        os.environ.get("PGBENCH_BINARY"),
        "/opt/homebrew/opt/postgresql@18/bin/pgbench",
        "/usr/lib/postgresql/18/bin/pgbench",
        shutil.which("pgbench"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            out = subprocess.run(  # noqa: S603 - fixed argv, test setup only
                [candidate, "--version"], capture_output=True, text=True, check=False
            ).stdout
            if " 18." in out or " 18 " in out or out.strip().endswith(" 18"):
                return candidate
    pytest.skip("pgbench 18 not found (set PGBENCH_BINARY)")


@dataclass(frozen=True)
class Server:
    major: int
    host: str
    port: int
    container: object

    def params(self, **overrides: object) -> ConnParams:
        base: dict[str, object] = {
            "host": self.host,
            "port": self.port,
            "dbname": "bench",
            "user": "bench",
            "sslmode": "prefer",
            "app_name": "pgbench-studio-it",
            "connect_timeout_s": 5,
            "password": PASSWORD,
        }
        base.update(overrides)
        return ConnParams(**base)  # type: ignore[arg-type]

    def psql(self, sql: str) -> None:
        code, out = self.container.exec(  # type: ignore[attr-defined]
            ["psql", "-v", "ON_ERROR_STOP=1", "-U", "bench", "-d", "bench", "-c", sql]
        )
        assert code == 0, out


@pytest.fixture(scope="session", params=SERVER_VERSIONS, ids=lambda v: f"pg{v}")
def server(request: pytest.FixtureRequest) -> Iterator[Server]:
    testcontainers = pytest.importorskip("testcontainers.postgres")
    try:
        container = testcontainers.PostgresContainer(
            f"postgres:{request.param}", username="bench", password=PASSWORD, dbname="bench"
        )
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker is not available: {exc}")
    try:
        yield Server(
            major=int(request.param),
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(5432)),
            container=container,
        )
    finally:
        container.stop()


@pytest.fixture(scope="session")
def pgbench() -> str:
    return pgbench_binary()

from __future__ import annotations

import contextlib
import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.connection import ConnFailure, ConnParams, ServerFacts
from app.main import create_app
from app.storage import repo
from app.storage.models import Role, User

# Fake pgbench: --version, and `-i` output modelled on pgbench 18. Behaviour is selected by
# PGDATABASE because the runner passes only PATH, LC_ALL, HOME and PG* to the child.
FAKE_PGBENCH = r"""#!/bin/sh
if [ "$1" = "--version" ]; then echo 'pgbench (PostgreSQL) 18.1'; exit 0; fi
case "$1" in
  --show-script=select-only)
    printf -- '-- select-only: <builtin: select only>\n\\set aid random(1, 100000 * :scale)\nSELECT abalance FROM pgbench_accounts WHERE aid = :aid;\n\n'; exit 0 ;;
  --show-script=*)
    name="${1#--show-script=}"; printf -- "-- $name: <builtin: $name title>\nSELECT 1;\n"; exit 0 ;;
esac
env > "$HOME/env.txt"
echo "$@" > "$HOME/argv.txt"
ls > "$HOME/files.txt"
if [ "$1" != "-i" ]; then
  case "$PGDATABASE" in
    failme) echo 'pgbench: error: client 0 aborted in command 1 (SQL) of script 0; ERROR:  boom' >&2; exit 2 ;;
    slow) exec sleep 30 ;;
  esac
  echo 'transaction type: multiple scripts'
  echo 'number of transactions actually processed: 1/1'
  exit 0
fi
case "$PGDATABASE" in
  failme) echo 'pgbench: error: connection to server failed: FATAL:  boom' >&2; exit 1 ;;
  slow) echo 'dropping old tables...' >&2; exec sleep 30 ;;
esac
echo 'dropping old tables...' >&2
echo 'creating tables...' >&2
echo 'generating data (client-side)...' >&2
printf '50000 of 100000 tuples (50%%) of pgbench_accounts done (elapsed 0.01 s, remaining 0.01 s)\r' >&2
echo '100000 of 100000 tuples (100%) of pgbench_accounts done (elapsed 0.02 s, remaining 0.00 s)' >&2
echo 'vacuuming...' >&2
echo 'creating primary keys...' >&2
echo 'done in 0.05 s (drop tables 0.00 s, create tables 0.00 s, client-side generate 0.02 s, vacuum 0.01 s, primary keys 0.02 s).' >&2
"""

ADMIN = "admin"
ADMIN_PASSWORD = "admin-password"
PASSWORD = "user-password"


@pytest.fixture
def fake_pgbench(tmp_path: Path) -> Path:
    script = tmp_path / "pgbench"
    script.write_text(FAKE_PGBENCH)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.fixture
def secret_env(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("PGB_STUDIO_SECRET_KEY", key)
    monkeypatch.setenv("PGB_STUDIO_ADMIN_USER", ADMIN)
    monkeypatch.setenv("PGB_STUDIO_ADMIN_PASSWORD", ADMIN_PASSWORD)
    return key


@pytest.fixture
def make_settings(tmp_path: Path, fake_pgbench: Path) -> Callable[..., Settings]:
    def factory(**sections: dict[str, Any]) -> Settings:
        data: dict[str, dict[str, Any]] = {
            "storage": {
                "sqlite_path": str(tmp_path / "data" / "studio.db"),
                "runs_dir": str(tmp_path / "data" / "runs"),
            },
            "pgbench": {"binary": str(fake_pgbench)},
            "limits": {"min_free_disk_gb": 0},
        }
        for name, values in sections.items():
            data.setdefault(name, {}).update(values)
        return Settings(**data)

    return factory


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings()


class Api:
    """TestClient wrapper with helpers for users and logins."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def run(self, fn: Callable[..., Any], *args: Any) -> Any:
        return self.client.portal.call(fn, *args)  # type: ignore[union-attr]

    def db_call(self, fn: Callable[..., Any], *args: Any) -> Any:
        async def inner() -> Any:
            async with self.client.app.state.sessionmaker() as db:  # type: ignore[attr-defined]
                result = await fn(db, *args)
                await db.commit()
                return result

        return self.run(inner)

    def add_user(
        self, username: str, role: Role, password: str = PASSWORD, must_change: bool = False
    ) -> User:
        async def create(db: Any) -> User:
            return await repo.create_user(db, username, password, role, must_change)

        user: User = self.db_call(create)
        return user

    def get_user(self, username: str) -> User:
        user: User = self.db_call(repo.get_user_by_username, username)
        return user

    def login(self, username: str, password: str = PASSWORD) -> Any:
        self.client.cookies.clear()
        return self.client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )

    def login_as(self, role: Role | None) -> None:
        """Log in as a fresh user with the given role; None means no session."""
        self.client.cookies.clear()
        if role is None:
            return
        name = f"user-{role.value}"
        with contextlib.suppress(Exception):  # the user may already exist
            self.add_user(name, role)
        resp = self.login(name)
        assert resp.status_code == 200, resp.text


class FakeChecker:
    """Stands in for the psycopg connection check; records what it was called with."""

    def __init__(self) -> None:
        self.calls: list[ConnParams] = []
        self.result: ServerFacts | ConnFailure = FACTS

    async def __call__(self, params: ConnParams) -> ServerFacts | ConnFailure:
        self.calls.append(params)
        return self.result


FACTS = ServerFacts(
    server_version="18.0",
    server_version_num=180000,
    response_ms=1.8,
    max_connections=200,
    reserved_connections=3,
    used_connections=13,
    pgbench_tables=True,
    scale=100,
    accounts_rows=10_000_000,
)


@pytest.fixture
def api(settings: Settings, secret_env: str) -> Iterator[Api]:
    app = create_app(settings)
    with TestClient(app, base_url="https://testserver") as client:
        app.state.connection_checker = FakeChecker()
        yield Api(client)

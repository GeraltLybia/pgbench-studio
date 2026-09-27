"""Database engine, sessions and Alembic migrations."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import ConnectionPoolEntry

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def sync_url(sqlite_path: Path) -> str:
    return f"sqlite:///{sqlite_path}"


def async_url(sqlite_path: Path) -> str:
    return f"sqlite+aiosqlite:///{sqlite_path}"


def _enable_foreign_keys(dbapi_conn: object, _record: ConnectionPoolEntry) -> None:
    cursor = dbapi_conn.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_engine_for(sqlite_path: Path) -> AsyncEngine:
    engine = create_async_engine(async_url(sqlite_path))
    event.listen(engine.sync_engine, "connect", _enable_foreign_keys)
    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def alembic_config(sqlite_path: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", sync_url(sqlite_path))
    return cfg


def run_migrations(sqlite_path: Path) -> None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(sqlite_path), "head")


def head_revision(sqlite_path: Path) -> str | None:
    return ScriptDirectory.from_config(alembic_config(sqlite_path)).get_current_head()

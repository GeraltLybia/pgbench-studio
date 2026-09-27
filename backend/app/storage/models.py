"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, TypeDecorator
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Stores naive UTC in SQLite and always returns timezone-aware UTC datetimes."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime is not allowed")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Role(StrEnum):
    viewer = "viewer"
    editor = "editor"
    admin = "admin"

    @property
    def level(self) -> int:
        return _ROLE_LEVEL[self]

    def allows(self, required: Role) -> bool:
        return self.level >= required.level


_ROLE_LEVEL = {Role.viewer: 0, Role.editor: 1, Role.admin: 2}


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    disabled: Mapped[bool] = mapped_column(default=False)
    must_change_password: Mapped[bool] = mapped_column(default=False)
    failed_attempts: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    last_login_ip: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    sessions: Mapped[list[Session]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def role_enum(self) -> Role:
        return Role(self.role)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    ip: Mapped[str | None] = mapped_column(String(64), default=None)

    user: Mapped[User] = relationship(back_populates="sessions")


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    dbname: Mapped[str] = mapped_column(String(63))
    user: Mapped[str] = mapped_column(String(63))
    sslmode: Mapped[str] = mapped_column(String(16))
    app_name: Mapped[str] = mapped_column(String(63))
    connect_timeout_s: Mapped[int] = mapped_column(Integer)
    password_enc: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class RunKind(StrEnum):
    init = "init"
    bench = "bench"


class RunStatus(StrEnum):
    queued = "queued"
    running = "running"
    finalizing = "finalizing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"

    @property
    def is_active(self) -> bool:
        return self in (RunStatus.queued, RunStatus.running, RunStatus.finalizing)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"), index=True, default=None
    )
    kind: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16))
    started_by: Mapped[str | None] = mapped_column(String(64), default=None)
    stopped_by: Mapped[str | None] = mapped_column(String(64), default=None)
    confirmed_rules_json: Mapped[str | None] = mapped_column(Text, default=None)
    config_json: Mapped[str] = mapped_column(Text)
    argv_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    server_version: Mapped[str | None] = mapped_column(String(64), default=None)
    pgbench_version: Mapped[str | None] = mapped_column(String(32), default=None)
    summary_json: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)


class Script(Base):
    __tablename__ = "scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    body: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

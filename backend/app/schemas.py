"""Pydantic models of the public API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.security.passwords import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from app.storage.models import Role

USERNAME_PATTERN = r"^[A-Za-z0-9._-]{3,64}$"


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    detail: ErrorDetail


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class Me(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Role
    must_change_password: bool


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Role
    disabled: bool
    must_change_password: bool
    locked_until: datetime | None
    last_login_at: datetime | None
    last_login_ip: str | None
    created_at: datetime


class UserCreate(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    role: Role


class UserUpdate(BaseModel):
    role: Role | None = None
    disabled: bool | None = None


class TemporaryPassword(BaseModel):
    user: UserOut
    temporary_password: str


HealthStatus = Literal["ok", "warning", "fail"]


class HealthCheckOut(BaseModel):
    name: str
    title: str
    required: bool
    status: HealthStatus
    value: str | None
    threshold: str | None
    message: str


class SystemHealth(BaseModel):
    status: HealthStatus
    checked_at: datetime
    checks: list[HealthCheckOut]


class Liveness(BaseModel):
    status: Literal["ok"]


class Readiness(BaseModel):
    status: Literal["ok", "fail"]
    failed: list[str]
    pgbench_version: str | None


class LimitsOut(BaseModel):
    connections_reserve: int
    max_duration_s: int
    max_transactions: int
    max_scale: int
    min_free_disk_gb: float


class SystemInfo(BaseModel):
    app_version: str
    agent_name: str
    pgbench_version: str | None
    dev_mode: bool
    cpu_warning_percent: int
    min_server_version: int
    limits: LimitsOut


# --- profiles and connection check -------------------------------------------------------

SslModeLiteral = Literal["disable", "prefer", "require", "verify-full"]

HOST_PATTERN = r"^[A-Za-z0-9._:\-\[\]]+$"
NO_NUL_PATTERN = r"^[^\x00]+$"
PRINTABLE_PATTERN = r"^[\x20-\x7e]*$"


class ConnectionFields(BaseModel):
    host: str = Field(min_length=1, max_length=255, pattern=HOST_PATTERN)
    port: int = Field(default=5432, ge=1, le=65535)
    dbname: str = Field(min_length=1, max_length=63, pattern=NO_NUL_PATTERN)
    user: str = Field(min_length=1, max_length=63, pattern=NO_NUL_PATTERN)
    sslmode: SslModeLiteral = "prefer"
    app_name: str = Field(default="pgbench-studio", max_length=63, pattern=PRINTABLE_PATTERN)
    connect_timeout_s: int = Field(default=10, ge=1, le=120)


Password = Annotated[str, StringConstraints(min_length=1, max_length=1024, pattern=NO_NUL_PATTERN)]


class ProfileCreate(ConnectionFields):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[^\x00-\x1f]+$")
    password: Password | None = None


class ProfileUpdate(ProfileCreate):
    # password: None keeps the stored one; clear_password removes it.
    clear_password: bool = False


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    host: str
    port: int
    dbname: str
    user: str
    sslmode: SslModeLiteral
    app_name: str
    connect_timeout_s: int
    has_password: bool
    created_at: datetime
    updated_at: datetime


class ConnectionTestRequest(ConnectionFields):
    # With profile_id and no password, the stored password of that profile is used.
    profile_id: int | None = None
    password: Password | None = None


class ConnectionTestOk(BaseModel):
    ok: Literal[True] = True
    checked_at: datetime
    server_version: str
    server_version_num: int
    server_major: int
    pgbench_version: str | None
    warnings: list[str]
    response_ms: float
    max_connections: int
    reserved_connections: int
    used_connections: int
    free_connections: int
    pgbench_tables: bool
    scale: int | None
    accounts_rows: int | None


class ConnectionTestFail(BaseModel):
    ok: Literal[False] = False
    checked_at: datetime
    code: Literal[
        "host_unreachable",
        "timeout",
        "connection_refused",
        "auth_failed",
        "database_not_found",
        "no_connect_privilege",
        "ssl_error",
        "unknown",
    ]
    message: str
    hint: str
    raw: str


class InitRequest(BaseModel):
    scale: int = Field(ge=1)
    fillfactor: int = Field(default=100, ge=10, le=100)
    foreign_keys: bool = True
    unlogged: bool = False
    confirm_dbname: str = Field(max_length=63)
    confirm_large: bool = False


class RunStarted(BaseModel):
    run_id: int


# --- runs --------------------------------------------------------------------------------


class InitProgressOut(BaseModel):
    done: int | None
    total: int | None
    pct: float | None
    elapsed_s: float | None
    remaining_s: float | None
    phase: str | None


class LogLineOut(BaseModel):
    stream: Literal["stdout", "stderr"]
    line: str


class RunOut(BaseModel):
    id: int
    kind: Literal["init", "bench"]
    status: Literal["queued", "running", "finalizing", "completed", "failed", "cancelled"]
    profile_id: int | None
    started_by: str | None
    stopped_by: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    pgbench_version: str | None
    server_version: str | None
    error: str | None
    argv: list[str]
    config: dict[str, Any]
    progress: InitProgressOut | None
    log_tail: list[LogLineOut]

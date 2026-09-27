"""Pydantic models of the public API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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

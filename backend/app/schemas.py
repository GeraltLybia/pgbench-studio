"""Pydantic models of the public API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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
    cpu_count: int
    default_progress_interval_s: int
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


class TotalsOut(BaseModel):
    """Counters pgbench prints for the whole run and for each script, exactly as printed."""

    processed: int | None = None
    tps: float | None = None
    failed: int | None = None
    failed_pct: float | None = None
    serialization_failures: int | None = None
    deadlock_failures: int | None = None
    retried: int | None = None
    retried_pct: float | None = None
    retries: int | None = None
    skipped: int | None = None
    skipped_pct: float | None = None
    latency_avg_ms: float | None = None
    latency_stddev_ms: float | None = None


class ScriptSummaryOut(TotalsOut):
    index: int
    name: str
    scenario: str | None = None
    weight: int | None = None
    weight_pct: float | None = None
    share_pct: float | None = None


class PgbenchSummaryOut(TotalsOut):
    pgbench_version: str | None = None
    server_version: str | None = None
    transaction_type: str | None = None
    scale: int | None = None
    query_mode: str | None = None
    clients: int | None = None
    threads: int | None = None
    max_tries: int | None = None
    duration_s: int | None = None
    transactions_per_client: int | None = None
    processed_target: int | None = None
    latency_limit_ms: float | None = None
    above_limit: int | None = None
    above_limit_pct: float | None = None
    lag_avg_ms: float | None = None
    lag_max_ms: float | None = None
    initial_connection_ms: float | None = None
    aborted: bool = False
    scripts: list[ScriptSummaryOut] = []


class Percentiles(BaseModel):
    p50: float | None = None
    p95: float | None = None
    p99: float | None = None


class RunSummaryOut(BaseModel):
    """`runs.summary_json`: pgbench's final report and how the series was obtained."""

    exit_code: int | None = None
    # pgbench printed its final report (not after SIGINT or a crash).
    complete: bool = False
    pgbench: PgbenchSummaryOut | None = None
    percentiles: Percentiles | None = None
    series_source: Literal["aggregate", "transactions", "progress"] | None = None
    sampling_rate: float | None = None
    parse_error: str | None = None


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
    summary: RunSummaryOut | None


class SeriesPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    t_s: int
    tx: int
    tps: float
    lat_avg_ms: float | None
    lat_min_ms: float | None
    lat_max_ms: float | None
    lat_std_ms: float | None
    lag_ms: float | None
    failed: int
    retried: int


class StatementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    script: str
    idx: int
    sql: str
    latency_ms: float
    failures: int | None


class HistogramBucketOut(BaseModel):
    upper_ms: float
    count: int


class RunFileOut(BaseModel):
    name: str
    size_bytes: int


class ReportOut(BaseModel):
    run: RunOut
    series: list[SeriesPointOut]
    statements: list[StatementOut]
    histogram: list[HistogramBucketOut]
    # pgbench's stdout: the final report, as printed.
    raw_output: str
    raw_output_truncated: bool
    files: list[RunFileOut]


# --- scripts and run configuration -------------------------------------------------------

SCRIPT_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
VARIABLE_NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,62}$"
MAX_SCRIPT_BYTES = 64 * 1024

ScriptBody = Annotated[str, StringConstraints(max_length=MAX_SCRIPT_BYTES)]


class ScriptIn(BaseModel):
    name: str = Field(pattern=SCRIPT_NAME_PATTERN)
    body: ScriptBody


class ScriptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    body: str
    updated_at: datetime


class ValidateRequest(BaseModel):
    body: ScriptBody
    server_major: int | None = Field(default=None, ge=9, le=99)
    # Variables that come from -D; they do not trigger «unknown variable».
    variables: list[Annotated[str, StringConstraints(pattern=VARIABLE_NAME_PATTERN)]] = []


class DiagnosticOut(BaseModel):
    line: int
    col: int
    end_col: int
    severity: Literal["error", "danger", "warning"]
    message: str
    rule: str | None


class ValidateResponse(BaseModel):
    diagnostics: list[DiagnosticOut]
    variables_used: list[str]
    variables_defined: list[str]
    has_errors: bool


class BuiltinOut(BaseModel):
    name: Literal["tpcb-like", "simple-update", "select-only"]
    title: str
    body: str


class BuiltinScenario(BaseModel):
    kind: Literal["builtin"]
    name: Literal["tpcb-like", "simple-update", "select-only"]
    weight: int = Field(default=1, ge=1, le=1000)


class ScriptScenario(BaseModel):
    kind: Literal["script"]
    name: str = Field(pattern=SCRIPT_NAME_PATTERN)
    body: ScriptBody
    weight: int = Field(default=1, ge=1, le=1000)
    # Library script it was taken from; the body above is what runs.
    script_id: int | None = None


Scenario = Annotated[BuiltinScenario | ScriptScenario, Field(discriminator="kind")]


class Variable(BaseModel):
    name: str = Field(pattern=VARIABLE_NAME_PATTERN)
    value: str = Field(max_length=256, pattern=r"^[^\x00]*$")


class RunConfig(BaseModel):
    profile_id: int
    mode: Literal["duration", "transactions"] = "duration"
    duration_s: int | None = Field(default=None, ge=1)
    transactions: int | None = Field(default=None, ge=1)
    clients: int = Field(default=1, ge=1, le=10_000)
    threads: int = Field(default=1, ge=1, le=1024)
    protocol: Literal["simple", "extended", "prepared"] = "simple"
    rate_tps: float | None = Field(default=None, gt=0)
    latency_limit_ms: float | None = Field(default=None, gt=0)
    vacuum: bool = True
    variables: list[Variable] = Field(default_factory=list, max_length=50)
    detailed_log: bool = False
    sampling_rate: float | None = Field(default=None, gt=0, le=1)
    scenarios: list[Scenario] = Field(min_length=1, max_length=20)
    confirmed_rules: list[str] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def _consistent(self) -> RunConfig:
        if self.mode == "duration" and self.duration_s is None:
            raise ValueError("duration_s is required in duration mode")
        if self.mode == "transactions" and self.transactions is None:
            raise ValueError("transactions is required in transactions mode")
        if self.sampling_rate is not None and not self.detailed_log:
            raise ValueError("sampling_rate is only allowed with detailed_log")
        names = [v.name for v in self.variables]
        if len(names) != len(set(names)):
            raise ValueError("variable names must be unique")
        return self


class DryRunRequest(BaseModel):
    profile_id: int
    protocol: Literal["simple", "extended", "prepared"] = "simple"
    variables: list[Variable] = Field(default_factory=list, max_length=50)
    scenario: Scenario
    confirmed_rules: list[str] = Field(default_factory=list, max_length=200)


class Finding(BaseModel):
    """A limit or script finding; `rule_id` is what goes into confirmed_rules."""

    rule_id: str
    level: Literal["error", "danger", "warning", "attention"]
    message: str
    field: str | None = None
    scenario: str | None = None
    line: int | None = None


class CommandPreview(BaseModel):
    argv: list[str]
    env: dict[str, str]
    command: str
    findings: list[Finding]


class DryRunResult(BaseModel):
    ok: bool
    exit_code: int | None
    duration_ms: float
    stdout: str
    stderr: str
    timed_out: bool


class ActiveRunOut(BaseModel):
    run_id: int | None
    kind: Literal["init", "bench"] | None
    status: Literal["queued", "running", "finalizing"] | None

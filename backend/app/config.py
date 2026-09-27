"""Agent settings: models, loading from config.yaml and PGB_STUDIO_* env overrides."""

from __future__ import annotations

import os
from ipaddress import IPv4Network, IPv6Network
from pathlib import Path
from typing import Any, Literal

import yaml
from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

CONFIG_PATH_ENV = "PGB_STUDIO_CONFIG"
DEFAULT_CONFIG_PATH = "config.yaml"


class ConfigError(Exception):
    """Raised when the configuration cannot be loaded; the message is shown to the operator."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServerSettings(_Section):
    host: str = "0.0.0.0"  # noqa: S104 - listens inside the compose network only
    port: int = Field(default=8000, ge=1, le=65535)
    trusted_proxies: list[IPv4Network | IPv6Network] = Field(default_factory=list)
    dev_mode: bool = False
    secret_key_env: str = Field(default="PGB_STUDIO_SECRET_KEY", min_length=1)


class AuthSettings(_Section):
    session_ttl_h: int = Field(default=12, ge=1)
    cookie_secure: bool = True
    max_failed_logins: int = Field(default=5, ge=1)
    lockout_min: int = Field(default=5, ge=1)
    admin_user_env: str = Field(default="PGB_STUDIO_ADMIN_USER", min_length=1)
    admin_password_env: str = Field(default="PGB_STUDIO_ADMIN_PASSWORD", min_length=1)


class StorageSettings(_Section):
    sqlite_path: Path = Path("/data/studio.db")
    runs_dir: Path = Path("/data/runs")
    keep_runs_days: int = Field(default=90, ge=1)


class PgbenchSettings(_Section):
    binary: str = Field(default="pgbench", min_length=1)
    max_parallel_runs: int = Field(default=1, ge=1)
    default_progress_interval_s: int = Field(default=1, ge=1)


class AgentSettings(_Section):
    name: str = Field(default="load-agent-01", min_length=1)
    sample_interval_s: int = Field(default=1, ge=1)
    cpu_warning_percent: int = Field(default=85, ge=1, le=100)


class LimitsSettings(_Section):
    connections_reserve: int = Field(default=5, ge=0)
    max_duration_s: int = Field(default=14400, ge=10)
    max_transactions: int = Field(default=100_000_000, ge=1)
    max_scale: int = Field(default=5000, ge=1)
    min_free_disk_gb: float = Field(default=5, ge=0)


class LoggingSettings(_Section):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PGB_STUDIO_",
        env_nested_delimiter="__",
        extra="forbid",
    )

    server: ServerSettings = Field(default_factory=ServerSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    pgbench: PgbenchSettings = Field(default_factory=PgbenchSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    limits: LimitsSettings = Field(default_factory=LimitsSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Environment overrides values from config.yaml (passed as init kwargs).
        return env_settings, init_settings

    @model_validator(mode="after")
    def _secure_cookie_outside_dev(self) -> Settings:
        if not self.auth.cookie_secure and not self.server.dev_mode:
            raise ValueError(
                "auth.cookie_secure: false допускается только при server.dev_mode: true"
            )
        return self

    def secret_key(self) -> bytes:
        """Return the Fernet key from the environment or raise ConfigError."""
        return resolve_secret_key(self.server.secret_key_env)


def resolve_secret_key(env_name: str) -> bytes:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        raise ConfigError(
            f"Не задан ключ шифрования: переменная окружения {env_name} пуста. "
            "Сгенерируйте ключ командой `studio gen-key` и передайте его через .env."
        )
    key = raw.encode()
    try:
        Fernet(key)
    except ValueError as exc:
        raise ConfigError(
            f"Ключ шифрования в {env_name} некорректен: нужен Fernet-ключ "
            "(32 байта в url-safe base64). Сгенерируйте его командой `studio gen-key`."
        ) from exc
    return key


def config_path() -> Path:
    return Path(os.environ.get(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH))


def _format_validation_error(path: Path, exc: ValidationError) -> str:
    lines = [f"Ошибка в конфигурации {path}:"]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "<корень>"
        line = f"  - {loc}: {err['msg']}"
        if err["type"] not in ("missing", "value_error") and "input" in err:
            line += f" (значение: {err['input']!r})"
        lines.append(line)
    return "\n".join(lines)


def load_settings(path: Path | None = None) -> Settings:
    """Load and validate settings. Any problem is reported as ConfigError."""
    path = path or config_path()
    if not path.is_file():
        raise ConfigError(
            f"Файл конфигурации не найден: {path}. Укажите путь в переменной {CONFIG_PATH_ENV}."
        )
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Ошибка в конфигурации {path}: некорректный YAML.\n{exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"Ошибка в конфигурации {path}: ожидался словарь секций на верхнем уровне."
        )
    try:
        return Settings(**data)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(path, exc)) from exc

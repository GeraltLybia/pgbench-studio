"""Individual agent health checks and a cached aggregate."""

from __future__ import annotations

import asyncio
import re
import shutil
import sqlite3
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import psutil

from app.config import ConfigError, Settings, resolve_secret_key
from app.storage.models import utcnow

Status = Literal["ok", "warning", "fail"]

_PGBENCH_VERSION_RE = re.compile(r"pgbench \(PostgreSQL\) (\d+)(?:\.(\d+))?")
_GB = 1024**3


@dataclass(frozen=True)
class CheckResult:
    name: str
    title: str
    required: bool
    status: Status
    message: str
    value: str | None = None
    threshold: str | None = None


def overall_status(results: list[CheckResult]) -> Status:
    if any(r.required and r.status == "fail" for r in results):
        return "fail"
    if any(r.status != "ok" for r in results):
        return "warning"
    return "ok"


def check_config(settings: Settings | None, path: Path | None) -> CheckResult:
    title = "Конфигурация"
    if settings is None:
        return CheckResult("config", title, True, "fail", "Конфигурация не загружена")
    return CheckResult(
        "config", title, True, "ok", "Конфигурация загружена и валидна", value=str(path or "")
    )


def check_secret_key(env_name: str) -> CheckResult:
    title = "Ключ шифрования"
    try:
        resolve_secret_key(env_name)
    except ConfigError as exc:
        return CheckResult("secret_key", title, True, "fail", str(exc), value=env_name)
    return CheckResult("secret_key", title, True, "ok", "Ключ задан", value=env_name)


def check_database(sqlite_path: Path, head: str | None) -> CheckResult:
    title = "База SQLite"
    try:
        conn = sqlite3.connect(f"file:{sqlite_path}?mode=rw", uri=True, timeout=2)
        try:
            (user_version,) = conn.execute("PRAGMA user_version").fetchone()
            # Rewriting the header value is a real write that fails on a read-only database.
            conn.execute(f"PRAGMA user_version = {int(user_version)}")
            conn.commit()
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return CheckResult(
            "database",
            title,
            True,
            "fail",
            f"База недоступна на запись: {exc}",
            value=str(sqlite_path),
        )
    current = row[0] if row else None
    if current != head:
        return CheckResult(
            "database",
            title,
            True,
            "fail",
            "Схема базы отстаёт от версии приложения: миграции не применены",
            value=str(current),
            threshold=str(head),
        )
    return CheckResult(
        "database",
        title,
        True,
        "ok",
        "Открывается на запись, миграции применены",
        value=str(current),
    )


def check_runs_dir(runs_dir: Path) -> CheckResult:
    title = "Каталог запусков"
    if not runs_dir.is_dir():
        return CheckResult(
            "runs_dir", title, True, "fail", "Каталог не существует", value=str(runs_dir)
        )
    try:
        with tempfile.NamedTemporaryFile(dir=runs_dir, prefix=".health-"):
            pass
    except OSError as exc:
        return CheckResult(
            "runs_dir",
            title,
            True,
            "fail",
            f"Нет прав на запись: {exc.strerror}",
            value=str(runs_dir),
        )
    return CheckResult("runs_dir", title, True, "ok", "Доступен на запись", value=str(runs_dir))


def check_disk(path: Path, min_free_gb: float) -> CheckResult:
    title = "Свободное место"
    try:
        free_gb = shutil.disk_usage(path).free / _GB
    except OSError as exc:
        return CheckResult("disk", title, True, "fail", f"Не удалось проверить: {exc.strerror}")
    value = f"{free_gb:.1f} ГБ"
    threshold = f"{min_free_gb:g} ГБ"
    if free_gb < min_free_gb:
        return CheckResult(
            "disk", title, True, "fail", "Свободного места меньше порога", value, threshold
        )
    if free_gb < 2 * min_free_gb:
        return CheckResult(
            "disk",
            title,
            True,
            "warning",
            "Свободного места меньше двойного порога",
            value,
            threshold,
        )
    return CheckResult("disk", title, True, "ok", "Места достаточно", value, threshold)


def parse_pgbench_version(output: str) -> str | None:
    match = _PGBENCH_VERSION_RE.search(output)
    if not match:
        return None
    return f"{match.group(1)}.{match.group(2) or 0}"


async def check_pgbench(binary: str, timeout_s: float = 5.0) -> CheckResult:
    title = "pgbench"
    try:
        proc = await asyncio.create_subprocess_exec(
            binary,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        return CheckResult(
            "pgbench", title, True, "fail", f"Бинарник не найден: {exc.strerror}", value=binary
        )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return CheckResult("pgbench", title, True, "fail", "pgbench --version не отвечает")
    version = parse_pgbench_version(out.decode(errors="replace"))
    if proc.returncode != 0 or version is None:
        return CheckResult(
            "pgbench", title, True, "fail", "Не удалось определить версию pgbench", value=binary
        )
    return CheckResult("pgbench", title, True, "ok", "Найден", value=version)


def check_agent_load(cpu_pct: float, ram_pct: float, cpu_warning_pct: int) -> CheckResult:
    title = "Нагрузка на агент"
    value = f"CPU {cpu_pct:.0f} % · RAM {ram_pct:.0f} %"
    threshold = f"CPU {cpu_warning_pct} %"
    if cpu_pct > cpu_warning_pct:
        return CheckResult(
            "agent_load",
            title,
            False,
            "warning",
            "CPU агента выше порога: упор в генератор нагрузки",
            value,
            threshold,
        )
    return CheckResult("agent_load", title, False, "ok", "В норме", value, threshold)


def sample_agent() -> tuple[float, float]:
    return psutil.cpu_percent(interval=None), psutil.virtual_memory().percent


class HealthService:
    """Runs all checks; results are cached so frequent probes stay cheap."""

    def __init__(
        self,
        settings: Settings,
        config_file: Path | None,
        schema_head: str | None,
        cache_ttl_s: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
        sampler: Callable[[], tuple[float, float]] = sample_agent,
    ) -> None:
        self.settings = settings
        self.config_file = config_file
        self.schema_head = schema_head
        self.cache_ttl_s = cache_ttl_s
        self._clock = clock
        self._sampler = sampler
        self._cached: tuple[float, datetime, list[CheckResult]] | None = None
        self._lock = asyncio.Lock()
        self.pgbench_version: str | None = None

    async def _collect(self) -> list[CheckResult]:
        s = self.settings
        pgbench = await check_pgbench(s.pgbench.binary)
        self.pgbench_version = pgbench.value if pgbench.status == "ok" else None
        blocking: list[Callable[[], CheckResult]] = [
            lambda: check_database(s.storage.sqlite_path, self.schema_head),
            lambda: check_runs_dir(s.storage.runs_dir),
            lambda: check_disk(s.storage.sqlite_path.parent, s.limits.min_free_disk_gb),
        ]
        io_results = await asyncio.gather(*(asyncio.to_thread(fn) for fn in blocking))
        cpu, ram = self._sampler()
        return [
            check_config(s, self.config_file),
            check_secret_key(s.server.secret_key_env),
            *io_results,
            pgbench,
            check_agent_load(cpu, ram, s.agent.cpu_warning_percent),
        ]

    async def results(self) -> tuple[datetime, list[CheckResult]]:
        async with self._lock:
            now = self._clock()
            if self._cached is None or now - self._cached[0] >= self.cache_ttl_s:
                self._cached = (now, utcnow(), await self._collect())
            return self._cached[1], self._cached[2]

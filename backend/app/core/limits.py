"""Load parameter checks, согласно документации («Параметры нагрузки»).

Errors block the run; warnings need an explicit confirmation. The frontend mirrors these
rules in validation/runConfig.ts; the backend is the one that enforces them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from app.config import LimitsSettings
from app.core.connection import MIN_SERVER_MAJOR

LONG_DURATION_S = 3600
MIN_DURATION_S = 10
NEAR_FREE_SHARE = 0.8

LimitLevel = Literal["error", "warning"]


@dataclass(frozen=True)
class LoadShape:
    mode: Literal["duration", "transactions"]
    clients: int
    threads: int
    duration_s: int | None = None
    transactions: int | None = None
    rate_tps: float | None = None
    latency_limit_ms: float | None = None


@dataclass(frozen=True)
class LimitFinding:
    code: str
    level: LimitLevel
    field: str
    message: str

    @property
    def rule_id(self) -> str:
        return f"limits.{self.code}"


def agent_cpu_count() -> int:
    """CPUs available to this process (respects container CPU sets on Linux)."""
    affinity = getattr(os, "sched_getaffinity", None)
    if affinity is not None:
        return len(affinity(0))
    return os.cpu_count() or 1  # pragma: no cover - macOS has no sched_getaffinity


def check_limits(
    shape: LoadShape,
    limits: LimitsSettings,
    *,
    free_connections: int | None,
    cpu_count: int,
    server_major: int | None,
    pgbench_major: int | None,
) -> list[LimitFinding]:
    found: list[LimitFinding] = []

    def add(code: str, level: LimitLevel, field: str, message: str) -> None:
        found.append(LimitFinding(code, level, field, message))

    if free_connections is not None:
        available = free_connections - limits.connections_reserve
        if shape.clients > available:
            add(
                "clients_over_free",
                "error",
                "clients",
                f"Клиентов больше, чем свободных соединений с учётом резерва: максимум "
                f"{max(available, 0)} (свободно {free_connections}, резерв "
                f"{limits.connections_reserve})",
            )
        elif shape.clients > NEAR_FREE_SHARE * available:
            add(
                "clients_near_free",
                "warning",
                "clients",
                f"Клиентов больше 80 % свободных соединений ({shape.clients} из {available})",
            )

    if shape.threads > shape.clients:
        add("threads_over_clients", "error", "threads", "Потоков -j больше, чем клиентов -c")
    if shape.threads > cpu_count:
        add(
            "threads_over_cores",
            "error",
            "threads",
            f"Потоков -j больше, чем ядер на агенте ({cpu_count})",
        )

    if shape.mode == "duration":
        duration = shape.duration_s or 0
        if duration < MIN_DURATION_S:
            add("duration_too_short", "error", "duration_s", "Длительность -T не меньше 10 с")
        elif duration > limits.max_duration_s:
            add(
                "duration_over_max",
                "error",
                "duration_s",
                f"Длительность -T больше допустимой: максимум {limits.max_duration_s} с",
            )
        elif duration > LONG_DURATION_S:
            add("duration_long", "warning", "duration_s", "Тест дольше часа")
    else:
        total = shape.clients * (shape.transactions or 0)
        if (shape.transactions or 0) < 1:
            add("transactions_missing", "error", "transactions", "Укажите число транзакций -t")
        elif total > limits.max_transactions:
            add(
                "transactions_over_max",
                "error",
                "transactions",
                f"Всего транзакций c × t = {total} больше допустимого {limits.max_transactions}",
            )

    if shape.rate_tps is not None and shape.rate_tps <= 0:
        add("rate_not_positive", "error", "rate_tps", "Ограничение TPS -R должно быть больше нуля")
    if shape.latency_limit_ms is not None and shape.latency_limit_ms <= 0:
        add(
            "latency_limit_not_positive",
            "error",
            "latency_limit_ms",
            "Latency limit должен быть больше нуля",
        )

    if server_major is not None and (
        server_major < MIN_SERVER_MAJOR or (pgbench_major and server_major > pgbench_major)
    ):
        add(
            "server_version",
            "warning",
            "profile_id",
            f"PostgreSQL {server_major} вне поддерживаемого диапазона "
            f"{MIN_SERVER_MAJOR}–{pgbench_major or 18}",
        )
    return found

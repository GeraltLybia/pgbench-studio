"""Comparing two runs: metric differences and what differs in how they were started."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Better = Literal["higher", "lower"]

# (key in the pgbench summary or percentiles, label, which direction is better)
METRICS: list[tuple[str, str, Better]] = [
    ("tps", "TPS", "higher"),
    ("latency_avg_ms", "Latency avg", "lower"),
    ("latency_stddev_ms", "Latency stddev", "lower"),
    ("p95", "p95", "lower"),
    ("p99", "p99", "lower"),
    ("processed", "Транзакций", "higher"),
    ("failed", "Ошибок", "lower"),
    ("initial_connection_ms", "Initial connection", "lower"),
]

_PARAMS: list[tuple[str, str]] = [
    ("mode", "Режим"),
    ("duration_s", "Длительность -T, с"),
    ("transactions", "Транзакций на клиента -t"),
    ("clients", "Клиенты -c"),
    ("threads", "Потоки -j"),
    ("protocol", "Протокол -M"),
    ("rate_tps", "Ограничение -R"),
    ("latency_limit_ms", "--latency-limit, мс"),
    ("vacuum", "Vacuum перед тестом"),
    ("detailed_log", "Подробный лог"),
    ("sampling_rate", "--sampling-rate"),
]


@dataclass(frozen=True)
class Side:
    """What is compared of one run: its pgbench summary, percentiles and stored config."""

    summary: dict[str, Any]
    percentiles: dict[str, Any]
    config: dict[str, Any]
    server_version: str | None
    note: str | None = None


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    a: float | None
    b: float | None
    diff_pct: float | None
    better: Better


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    a: str | None
    b: str | None


def _value(side: Side, key: str) -> float | None:
    raw = side.percentiles.get(key) if key in ("p50", "p95", "p99") else side.summary.get(key)
    return float(raw) if isinstance(raw, int | float) and not isinstance(raw, bool) else None


def diff_pct(a: float | None, b: float | None) -> float | None:
    """How much a differs from b, in percent of b (+22.9 means a is 22.9 % higher)."""
    if a is None or b is None or b == 0:
        return None
    return round((a - b) / b * 100, 1)


def metric_diffs(a: Side, b: Side) -> list[Metric]:
    result: list[Metric] = []
    for key, label, better in METRICS:
        va, vb = _value(a, key), _value(b, key)
        if va is None and vb is None:
            continue
        result.append(Metric(key, label, va, vb, diff_pct(va, vb), better))
    return result


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "да" if value else "нет"
    return str(value)


def _scenarios(config: dict[str, Any]) -> list[dict[str, Any]]:
    run_config = config.get("run_config") or {}
    scenarios = run_config.get("scenarios") or []
    return [s for s in scenarios if isinstance(s, dict)]


def _variables(config: dict[str, Any]) -> str | None:
    variables = (config.get("run_config") or {}).get("variables") or []
    return " ".join(f"{v['name']}={v['value']}" for v in variables) or None


def param_diffs(a: Side, b: Side) -> list[Param]:
    """Only what differs: load parameters, scenarios and their texts, profile, server, scale."""
    ra, rb = a.config.get("run_config") or {}, b.config.get("run_config") or {}
    result: list[Param] = []

    def add(key: str, label: str, va: Any, vb: Any) -> None:
        ta, tb = _text(va), _text(vb)
        if ta != tb:
            result.append(Param(key, label, ta, tb))

    add("profile", "Профиль", a.config.get("profile_name"), b.config.get("profile_name"))
    add("server", "Сервер", a.server_version, b.server_version)
    add("scale", "Scale", a.summary.get("scale"), b.summary.get("scale"))
    for key, label in _PARAMS:
        add(key, label, ra.get(key), rb.get(key))
    add("variables", "Переменные -D", _variables(a.config), _variables(b.config))

    sa, sb = _scenarios(a.config), _scenarios(b.config)
    names_a = ", ".join(f"{s['name']}@{s.get('weight', 1)}" for s in sa)
    names_b = ", ".join(f"{s['name']}@{s.get('weight', 1)}" for s in sb)
    add("scenarios", "Сценарии", names_a or None, names_b or None)
    # Same script name, different text: the SQL itself changed between the runs.
    bodies_b = {s["name"]: s.get("body") for s in sb if s.get("kind") == "script"}
    for s in sa:
        name = s["name"]
        if s.get("kind") == "script" and name in bodies_b and s.get("body") != bodies_b[name]:
            label = f"Текст сценария {name}"
            result.append(Param(f"body:{name}", label, "отличается", "отличается"))
    return result

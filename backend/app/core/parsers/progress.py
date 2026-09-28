"""Progress lines of pgbench: `pgbench -i` data generation and phases."""

from __future__ import annotations

import re
from dataclasses import dataclass

_TUPLES_RE = re.compile(
    r"^(?P<done>\d+) of (?P<total>\d+) tuples \((?P<pct>\d+)%\) (?:of \S+ )?done"
    r"(?: \(elapsed (?P<elapsed>[\d.]+) s, remaining (?P<remaining>[\d.]+) s\))?"
)

# Phase headers printed by `pgbench -i` before each step.
_PHASES = {
    "dropping old tables...": "Удаление старых таблиц",
    "creating tables...": "Создание таблиц",
    "generating data (client-side)...": "Генерация данных",
    "generating data (server-side)...": "Генерация данных",
    "vacuuming...": "VACUUM",
    "creating primary keys...": "Первичные ключи",
    "creating foreign keys...": "Внешние ключи",
}


@dataclass(frozen=True)
class InitProgress:
    done: int
    total: int
    pct: float
    elapsed_s: float | None
    remaining_s: float | None


def parse_init_progress(line: str) -> InitProgress | None:
    match = _TUPLES_RE.match(line.strip())
    if not match:
        return None
    done, total = int(match["done"]), int(match["total"])
    return InitProgress(
        done=done,
        total=total,
        pct=round(100.0 * done / total, 1) if total else 100.0,
        elapsed_s=float(match["elapsed"]) if match["elapsed"] else None,
        remaining_s=float(match["remaining"]) if match["remaining"] else None,
    )


def parse_init_phase(line: str) -> str | None:
    text = line.strip()
    if text.startswith("done in "):
        return "Готово"
    return _PHASES.get(text)


# `progress: 5.0 s, 6085.0 tps, lat 1.292 ms stddev 0.345, 0 failed[, lag 0.8 ms][, 4 skipped]
#  [, 0 retried, 0 retries]` — pgbench 18 (failed/retried/skipped appeared in 15).
_BENCH_RE = re.compile(
    r"^progress: (?P<t>[\d.]+) s, (?P<tps>[\d.]+) tps, lat (?P<lat>[\d.]+) ms"
    r" stddev (?P<stddev>[\d.]+|NaN)"
    r"(?:, (?P<failed>\d+) failed)?"
    r"(?:, lag (?P<lag>[\d.]+) ms)?"
    r"(?:, (?P<skipped>\d+) skipped)?"
    r"(?:, (?P<retried>\d+) retried, (?P<retries>\d+) retries)?"
)


@dataclass(frozen=True)
class BenchProgress:
    t: float
    tps: float
    lat_ms: float
    stddev_ms: float | None
    lag_ms: float | None
    failed: int
    skipped: int
    retried: int


def parse_bench_progress(line: str) -> BenchProgress | None:
    match = _BENCH_RE.match(line.strip())
    if not match:
        return None
    stddev = match["stddev"]
    return BenchProgress(
        t=float(match["t"]),
        tps=float(match["tps"]),
        lat_ms=float(match["lat"]),
        stddev_ms=None if stddev == "NaN" else float(stddev),
        lag_ms=float(match["lag"]) if match["lag"] else None,
        failed=int(match["failed"] or 0),
        skipped=int(match["skipped"] or 0),
        retried=int(match["retried"] or 0),
    )


class ProgressEstimator:
    """Completion share and time left.

    `-T`: exact, t / T. `-t`: an estimate — transactions accumulated as tps × interval
    against clients × transactions (docs/architecture.md, «Раннер pgbench»).
    """

    def __init__(
        self,
        mode: str,
        duration_s: int | None = None,
        clients: int = 1,
        transactions: int | None = None,
    ) -> None:
        self.mode = mode
        self.duration_s = duration_s
        self.total_tx = clients * (transactions or 0)
        self.done_tx = 0.0
        self._last_t = 0.0

    @property
    def estimated(self) -> bool:
        return self.mode != "duration"

    def update(self, progress: BenchProgress) -> tuple[float | None, float | None]:
        """(pct, eta_s) after this progress line."""
        interval = max(progress.t - self._last_t, 0.0)
        self._last_t = progress.t
        if self.mode == "duration" and self.duration_s:
            pct = min(100.0, 100.0 * progress.t / self.duration_s)
            return round(pct, 2), max(self.duration_s - progress.t, 0.0)
        if self.total_tx <= 0:
            return None, None
        self.done_tx += progress.tps * interval
        pct = min(100.0, 100.0 * self.done_tx / self.total_tx)
        left = max(self.total_tx - self.done_tx, 0.0)
        eta = left / progress.tps if progress.tps > 0 else None
        return round(pct, 2), round(eta, 1) if eta is not None else None

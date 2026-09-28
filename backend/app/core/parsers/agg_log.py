"""The `-l --aggregate-interval` log: one file per thread, merged into one series.

pgbench 18 always writes 15 fields per interval (microseconds):
interval_start num_transactions sum_latency sum_latency_2 min_latency max_latency
sum_lag sum_lag_2 min_lag max_lag skipped retried retries serialization_failures
deadlock_failures. Failures are non-zero only with --failures-detailed; lag only
with --rate; skipped only with --latency-limit; retries only with --max-tries.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

LOG_PREFIX = "pgbench_log"


@dataclass(frozen=True)
class SeriesPoint:
    """One interval of the run, the same shape whichever log it comes from."""

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
    skipped: int


@dataclass
class Bucket:
    """Running sums for one interval (latencies in microseconds)."""

    tx: int = 0
    lat_sum: float = 0.0
    lat_sum2: float = 0.0
    lat_min: float = math.inf
    lat_max: float = -math.inf
    lag_sum: float = 0.0
    lag_count: int = 0
    failed: int = 0
    retried: int = 0
    skipped: int = 0

    def add_latency(self, sum_: float, sum2: float, min_: float, max_: float, count: int) -> None:
        if count <= 0:
            return
        self.tx += count
        self.lat_sum += sum_
        self.lat_sum2 += sum2
        self.lat_min = min(self.lat_min, min_)
        self.lat_max = max(self.lat_max, max_)

    def point(self, t_s: int, interval_s: float, scale: float = 1.0) -> SeriesPoint:
        """`scale` turns a sampled count (--sampling-rate) back into an estimate."""
        has_lat = self.tx > 0
        mean = self.lat_sum / self.tx if has_lat else 0.0
        variance = max(self.lat_sum2 / self.tx - mean * mean, 0.0) if has_lat else 0.0
        return SeriesPoint(
            t_s=t_s,
            tx=round(self.tx * scale),
            tps=round(self.tx * scale / interval_s, 3),
            lat_avg_ms=_ms(mean) if has_lat else None,
            lat_min_ms=_ms(self.lat_min) if has_lat else None,
            lat_max_ms=_ms(self.lat_max) if has_lat else None,
            lat_std_ms=_ms(math.sqrt(variance)) if has_lat else None,
            lag_ms=_ms(self.lag_sum / self.lag_count) if self.lag_count else None,
            failed=round(self.failed * scale),
            retried=round(self.retried * scale),
            skipped=round(self.skipped * scale),
        )


def _ms(us: float) -> float:
    return round(us / 1000, 3)


def log_files(run_dir: Path) -> list[Path]:
    """pgbench_log.<pid> and pgbench_log.<pid>.<thread>, plain or gzipped by the runner."""
    return sorted(p for p in run_dir.glob(f"{LOG_PREFIX}.*") if p.is_file() and not p.is_symlink())


def _read_file(path: Path, buckets: dict[int, Bucket]) -> None:
    with path.open(encoding="ascii", errors="replace") as fh:
        for line in fh:
            fields = line.split()
            if len(fields) < 6:
                continue
            try:
                values = [int(float(f)) for f in fields]
            except ValueError:
                continue
            start, count, sum_, sum2, min_, max_ = values[:6]
            bucket = buckets.setdefault(start, Bucket())
            bucket.add_latency(sum_, sum2, min_, max_, count)
            if len(values) >= 15:
                lag_sum = values[6]
                if lag_sum:
                    bucket.lag_sum += lag_sum
                    bucket.lag_count += count
                bucket.skipped += values[10]
                bucket.retried += values[11]
                bucket.failed += values[13] + values[14]


def parse_agg_logs(paths: Iterable[Path], interval_s: float = 1.0) -> list[SeriesPoint]:
    """Merge per-thread files by interval_start: sums add up, min and max over all files."""
    buckets: dict[int, Bucket] = {}
    for path in paths:
        _read_file(path, buckets)
    if not buckets:
        return []
    first = min(buckets)
    return [buckets[start].point(start - first, interval_s) for start in sorted(buckets)]

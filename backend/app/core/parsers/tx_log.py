"""The per-transaction `-l` log (detailed mode): per-second series and a latency histogram.

Line format (pgbench 18, microseconds):
client_id transaction_no latency script_no time_epoch time_us [schedule_lag] [retries]
`latency` is `failed` (or `serialization` / `deadlock`) for a failed transaction and
`skipped` for one skipped by --latency-limit. Files are read line by line, so a
long run does not have to fit in memory; only histogram buckets are kept.
"""

from __future__ import annotations

import gzip
import math
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from app.core.parsers.agg_log import Bucket, SeriesPoint

# Logarithmic buckets 1 % wide: percentiles are within 1 % of the exact value
# (exact below ~100 µs, where a bucket holds a single integer microsecond).
BUCKET_RATIO = 1.01
_LOG_RATIO = math.log(BUCKET_RATIO)
FAILED_MARKERS = frozenset({"failed", "serialization", "deadlock"})


def bucket_index(latency_us: int) -> int:
    return -1 if latency_us < 1 else math.floor(math.log(latency_us) / _LOG_RATIO + 1e-9)


def bucket_upper_ms(index: int) -> float:
    """Upper edge of a bucket; bucket -1 holds 0 µs."""
    return 0.001 if index < 0 else round(BUCKET_RATIO ** (index + 1) / 1000, 6)


@dataclass
class HistBucket:
    count: int = 0
    lo: int = 0  # smallest and largest latency seen, in µs
    hi: int = 0


@dataclass
class TxLogResult:
    series: list[SeriesPoint]
    histogram: list[tuple[float, int]]  # (bucket_upper_ms, count), non-empty buckets
    percentiles: dict[str, float]  # p50, p95, p99 in ms
    transactions: int  # successful transactions in the log (sampled ones only)
    failed: int
    skipped: int


@dataclass
class _State:
    seconds: dict[int, Bucket] = field(default_factory=dict)
    hist: dict[int, HistBucket] = field(default_factory=dict)
    transactions: int = 0
    failed: int = 0
    skipped: int = 0


def _read(fh: IO[str], state: _State, with_lag: bool) -> None:
    for line in fh:
        fields = line.split()
        if len(fields) < 6 or not fields[4].isdigit():
            continue
        second = int(fields[4])
        bucket = state.seconds.setdefault(second, Bucket())
        latency = fields[2]
        if latency in FAILED_MARKERS:
            bucket.failed += 1
            state.failed += 1
            continue
        if latency == "skipped":
            bucket.skipped += 1
            state.skipped += 1
            continue
        if not latency.isdigit():
            continue
        us = int(latency)
        bucket.add_latency(us, us * us, us, us, 1)
        if with_lag and len(fields) > 6 and fields[6].isdigit():
            bucket.lag_sum += int(fields[6])
            bucket.lag_count += 1
        state.transactions += 1
        hb = state.hist.get(index := bucket_index(us))
        if hb is None:
            state.hist[index] = HistBucket(1, us, us)
        else:
            hb.count += 1
            hb.lo = min(hb.lo, us)
            hb.hi = max(hb.hi, us)


def percentile(hist: dict[int, HistBucket], total: int, p: float) -> float | None:
    """Nearest-rank percentile in ms, interpolated between the bucket's min and max."""
    if total <= 0:
        return None
    rank = max(math.ceil(p * total), 1)
    seen = 0
    for index in sorted(hist):
        hb = hist[index]
        if seen + hb.count >= rank:
            fraction = (rank - seen) / hb.count if hb.count > 1 else 1.0
            return round((hb.lo + (hb.hi - hb.lo) * fraction) / 1000, 3)
        seen += hb.count
    return None  # pragma: no cover - rank never exceeds total


def parse_tx_logs(
    paths: Iterable[Path], *, with_lag: bool = False, sampling_rate: float | None = None
) -> TxLogResult:
    state = _State()
    for path in paths:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="ascii", errors="replace") as fh:
            _read(fh, state, with_lag)

    # A sampled log holds `rate` of the transactions: counts are scaled back.
    scale = 1 / sampling_rate if sampling_rate else 1.0
    first = min(state.seconds) if state.seconds else 0
    series = [state.seconds[s].point(s - first, 1.0, scale) for s in sorted(state.seconds)]
    percentiles = {
        name: value
        for name, p in (("p50", 0.50), ("p95", 0.95), ("p99", 0.99))
        if (value := percentile(state.hist, state.transactions, p)) is not None
    }
    return TxLogResult(
        series=series,
        histogram=[(bucket_upper_ms(i), state.hist[i].count) for i in sorted(state.hist)],
        percentiles=percentiles,
        transactions=state.transactions,
        failed=state.failed,
        skipped=state.skipped,
    )


def gzip_logs(paths: Iterable[Path]) -> list[Path]:
    """Compress parsed per-transaction logs in place (`name` -> `name.gz`)."""
    result: list[Path] = []
    for path in paths:
        if path.suffix == ".gz":
            result.append(path)
            continue
        target = path.with_name(path.name + ".gz")
        # Written aside and renamed: an interrupted run never leaves a truncated .gz.
        partial = path.with_name(path.name + ".gz.part")
        with path.open("rb") as src, gzip.open(partial, "wb") as dst:
            shutil.copyfileobj(src, dst)
        partial.replace(target)
        path.unlink()
        result.append(target)
    return result

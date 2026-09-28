"""The summary pgbench 18 prints to stdout when a benchmark ends.

Numbers are kept exactly as printed: a float keeps the printed decimal digits
(`float("14339.846214")` round-trips), so the report matches pgbench to the last digit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.parsers.statements import Columns, Statement, parse_header, parse_row

ABORTED_MARKER = "Run was aborted"

_VERSION = re.compile(
    r"^pgbench \((?P<client>[^\s(),]+)(?: \([^)]*\))?"
    r"(?:, server (?P<server>[^\s(),]+)(?: \([^)]*\))?)?\)$"
)
_SCRIPT = re.compile(r"^SQL script (?P<n>\d+): (?P<name>.+)$")
_NUM = r"(?P<n>\d+)"
_PCT = r"\((?P<pct>[\d.]+)%\)"
_MS = r"(?P<v>[\d.]+) ms"
_PROCESSED = r"^number of transactions actually processed: " + _NUM
_TPS_NOTE = r"\((?:without initial connection time|including reconnection times)\)"


@dataclass
class Totals:
    """Counters printed both for the whole run and for each script block."""

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


@dataclass
class ScriptSummary(Totals):
    index: int = 1
    name: str = ""
    weight: int | None = None
    weight_pct: float | None = None
    share_pct: float | None = None
    statements: list[Statement] = field(default_factory=list)


@dataclass
class Summary(Totals):
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
    scripts: list[ScriptSummary] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """pgbench reached its final report (it does not after a crash or SIGINT)."""
        return self.tps is not None


# Lines that may appear at the top level and, with " - ", inside a script block.
_COMMON: list[tuple[re.Pattern[str], str]] = [
    (re.compile(_PROCESSED + r"(?:/(?P<of>\d+))?$"), "processed"),
    (re.compile(_PROCESSED + r" \(tps = (?P<v>[\d.]+)\)$"), "processed_tps"),
    (re.compile(rf"^number of failed transactions: {_NUM} {_PCT}$"), "failed"),
    (re.compile(rf"^number of serialization failures: {_NUM} {_PCT}$"), "serialization_failures"),
    (re.compile(rf"^number of deadlock failures: {_NUM} {_PCT}$"), "deadlock_failures"),
    (re.compile(rf"^number of transactions retried: {_NUM} {_PCT}$"), "retried"),
    (re.compile(rf"^total number of retries: {_NUM}$"), "retries"),
    (re.compile(rf"^number of transactions skipped: {_NUM} {_PCT}$"), "skipped"),
    (re.compile(rf"^latency average = {_MS}(?: \(including failures\))?$"), "latency_avg_ms"),
    (re.compile(rf"^latency stddev = {_MS}$"), "latency_stddev_ms"),
]  # fmt: skip

_TOP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^transaction type: (?P<v>.+)$"), "transaction_type"),
    (re.compile(r"^scaling factor: (?P<v>\d+)$"), "scale"),
    (re.compile(r"^query mode: (?P<v>\w+)$"), "query_mode"),
    (re.compile(r"^number of clients: (?P<v>\d+)$"), "clients"),
    (re.compile(r"^number of threads: (?P<v>\d+)$"), "threads"),
    (re.compile(r"^maximum number of tries: (?P<v>\d+)$"), "max_tries"),
    (re.compile(r"^duration: (?P<v>\d+) s$"), "duration_s"),
    (re.compile(r"^number of transactions per client: (?P<v>\d+)$"), "transactions_per_client"),
    (re.compile(r"^initial connection time = (?P<v>[\d.]+) ms$"), "initial_connection_ms"),
    (re.compile(rf"^tps = (?P<v>[\d.]+) {_TPS_NOTE}$"), "tps"),
]  # fmt: skip

_ABOVE_LIMIT = re.compile(
    r"^number of transactions above the (?P<limit>[\d.]+) ms latency limit: "
    r"(?P<n>\d+)/\d+ \((?P<pct>[\d.]+)%\)$"
)
_LAG = re.compile(r"^rate limit schedule lag: avg (?P<avg>[\d.]+) \(max (?P<max>[\d.]+)\) ms$")
_WEIGHT = re.compile(r"^weight: (?P<n>\d+) \(targets (?P<pct>[\d.]+)% of total\)$")
_SHARE = re.compile(r"^(?P<n>\d+) transactions \((?P<pct>[\d.]+)% of total\)$")

_INT_FIELDS = {"scale", "clients", "threads", "max_tries", "duration_s", "transactions_per_client"}


def _apply_common(target: Totals, key: str, match: re.Match[str]) -> None:
    groups = match.groupdict()
    if key == "processed":
        target.processed = int(groups["n"])
        if groups.get("of") and isinstance(target, Summary):
            target.processed_target = int(groups["of"])
    elif key == "processed_tps":
        target.processed = int(groups["n"])
        target.tps = float(groups["v"])
    elif key in ("latency_avg_ms", "latency_stddev_ms"):
        setattr(target, key, float(groups["v"]))
    else:
        setattr(target, key, int(groups["n"]))
        if groups.get("pct") is not None and hasattr(target, f"{key}_pct"):
            setattr(target, f"{key}_pct", float(groups["pct"]))


def _apply_top(summary: Summary, line: str) -> bool:
    for pattern, key in _TOP:
        match = pattern.match(line)
        if match is not None:
            value = match["v"]
            setattr(summary, key, int(value) if key in _INT_FIELDS else _float_or_str(key, value))
            return True
    if match := _ABOVE_LIMIT.match(line):
        summary.latency_limit_ms = float(match["limit"])
        summary.above_limit = int(match["n"])
        summary.above_limit_pct = float(match["pct"])
        return True
    if match := _LAG.match(line):
        summary.lag_avg_ms = float(match["avg"])
        summary.lag_max_ms = float(match["max"])
        return True
    return False


def _float_or_str(key: str, value: str) -> float | str:
    return float(value) if key in ("initial_connection_ms", "tps") else value


def parse_summary(stdout: str, stderr: str = "") -> Summary:
    """Parse pgbench's stdout; stderr only tells whether the run was aborted."""
    summary = Summary(aborted=ABORTED_MARKER in stderr)
    script: ScriptSummary | None = None
    columns: Columns | None = None

    for raw in stdout.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if match := _VERSION.match(line):
            summary.pgbench_version = match["client"]
            summary.server_version = match["server"]
            continue
        if match := _SCRIPT.match(line):
            script = ScriptSummary(index=int(match["n"]), name=match["name"])
            summary.scripts.append(script)
            columns = None
            continue
        if (header := parse_header(line)) is not None:
            columns = header
            if script is None:
                # One script: its block is folded into the top-level lines.
                script = ScriptSummary(index=1, name=summary.transaction_type or "")
                summary.scripts.append(script)
            continue
        if columns is not None and script is not None:
            row = parse_row(line, columns, script.index, len(script.statements))
            if row is not None:
                script.statements.append(row)
                continue
            columns = None

        in_block = line.startswith(" - ")
        body = line[3:] if in_block else line
        target: Totals = script if in_block and script is not None else summary
        if in_block and script is not None:
            if match := _WEIGHT.match(body):
                script.weight = int(match["n"])
                script.weight_pct = float(match["pct"])
                continue
            if match := _SHARE.match(body):
                script.share_pct = float(match["pct"])
                continue
        for pattern, key in _COMMON:
            if match := pattern.match(body):
                _apply_common(target, key, match)
                break
        else:
            if not in_block:
                _apply_top(summary, line)

    if len(summary.scripts) == 1 and summary.scripts[0].processed is None:
        _inherit_single(summary)
    return summary


def _inherit_single(summary: Summary) -> None:
    """With one script pgbench prints no script block: its numbers are the totals."""
    only = summary.scripts[0]
    for name in Totals.__dataclass_fields__:
        setattr(only, name, getattr(summary, name))
    only.share_pct = 100.0 if summary.processed is not None else None

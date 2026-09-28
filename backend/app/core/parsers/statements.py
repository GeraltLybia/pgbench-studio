"""The `-r` table: per-statement latency, failures and retries of each script."""

from __future__ import annotations

import re
from dataclasses import dataclass

# "statement latencies in milliseconds and failures:" or "..., failures and retries:";
# with several scripts it is prefixed with " - " inside the script block.
HEADER = re.compile(r"^(?: - )?statement latencies in milliseconds(?P<cols>.*):$")
_ROW = re.compile(r"^\s+(?P<lat>\d+\.\d+)\s+(?P<rest>.*)$")


@dataclass(frozen=True)
class Statement:
    script: int  # 1-based script number, as in «SQL script N»
    idx: int  # 0-based position inside the script
    latency_ms: float
    failures: int | None
    retries: int | None
    command: str

    @property
    def is_meta(self) -> bool:
        return self.command.startswith("\\")


@dataclass(frozen=True)
class Columns:
    failures: bool
    retries: bool


def parse_header(line: str) -> Columns | None:
    match = HEADER.match(line)
    if match is None:
        return None
    cols = match["cols"]
    return Columns(failures="failures" in cols, retries="retries" in cols)


def parse_row(line: str, columns: Columns, script: int, idx: int) -> Statement | None:
    """One table row: `   0.059       67405 UPDATE ...` (failures and retries are optional)."""
    match = _ROW.match(line)
    if match is None:
        return None
    rest = match["rest"]
    counters: list[int] = []
    for _ in range(int(columns.failures) + int(columns.retries)):
        head, _, tail = rest.lstrip().partition(" ")
        if not head.isdigit():
            return None
        counters.append(int(head))
        rest = tail
    failures = counters[0] if columns.failures else None
    retries = counters[-1] if columns.retries else None
    return Statement(
        script=script,
        idx=idx,
        latency_ms=float(match["lat"]),
        failures=failures,
        retries=retries,
        command=rest.strip(),
    )

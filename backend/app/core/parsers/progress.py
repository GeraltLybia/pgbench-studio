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

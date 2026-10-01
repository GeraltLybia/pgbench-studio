"""Enforce per-directory coverage thresholds from a coverage.py JSON report.

85 % for app/core and app/api, 70 % for the rest of app/ (согласно документации, «Тестирование»).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

THRESHOLDS = {"app/core": 85.0, "app/api": 85.0}
DEFAULT_THRESHOLD = 70.0


def group_of(filename: str) -> str:
    for prefix in THRESHOLDS:
        if filename.startswith(prefix + "/"):
            return prefix
    return "app (прочее)"


def main(report_path: str = "coverage.json") -> int:
    files = json.loads(Path(report_path).read_text())["files"]
    totals: dict[str, list[int]] = {}
    for filename, data in files.items():
        summary = data["summary"]
        covered = summary["covered_lines"] + summary.get("covered_branches", 0)
        total = summary["num_statements"] + summary.get("num_branches", 0)
        acc = totals.setdefault(group_of(filename), [0, 0])
        acc[0] += covered
        acc[1] += total

    failed = False
    for group, (covered, total) in sorted(totals.items()):
        percent = 100.0 * covered / total if total else 100.0
        threshold = THRESHOLDS.get(group, DEFAULT_THRESHOLD)
        mark = "ok" if percent >= threshold else "FAIL"
        failed |= percent < threshold
        print(f"{group:<16} {percent:6.2f} % (порог {threshold:.0f} %) {mark}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))

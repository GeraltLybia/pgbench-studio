"""Builds a run's report from its directory once pgbench has exited (status finalizing)."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.core.parsers.agg_log import SeriesPoint, log_files, parse_agg_logs
from app.core.parsers.progress import parse_bench_progress
from app.core.parsers.statements import Statement
from app.core.parsers.summary import Summary, parse_summary
from app.core.parsers.tx_log import gzip_logs, parse_tx_logs

log = logging.getLogger(__name__)

SeriesSource = Literal["aggregate", "transactions", "progress"]
_ABORT_MARK = " aborted in command "


@dataclass(frozen=True)
class ReportOptions:
    """What the report needs to know about the run's command line."""

    detailed: bool = False
    with_lag: bool = False
    sampling_rate: float | None = None
    progress_interval_s: int = 1
    # Scenario names in the order of -b/-f: pgbench numbers scripts the same way.
    scripts: list[str] = field(default_factory=list)


@dataclass
class RunReport:
    summary: Summary
    series: list[SeriesPoint] = field(default_factory=list)
    series_source: SeriesSource | None = None
    histogram: list[tuple[float, int]] = field(default_factory=list)
    percentiles: dict[str, float] = field(default_factory=dict)
    error: str | None = None

    def statements(self, names: list[str]) -> list[tuple[str, Statement]]:
        """(script name, row) for every -r row; the name comes from the run's scenarios."""
        rows: list[tuple[str, Statement]] = []
        for script in self.summary.scripts:
            index = script.index - 1
            name = names[index] if 0 <= index < len(names) else script.name
            rows += [(name, st) for st in script.statements]
        return rows

    def summary_json(self, options: ReportOptions) -> dict[str, Any]:
        pgbench = asdict(self.summary)
        for script, block in zip(self.summary.scripts, pgbench["scripts"], strict=True):
            index = script.index - 1
            block["scenario"] = options.scripts[index] if index < len(options.scripts) else None
            del block["statements"]
        return {
            "pgbench": pgbench,
            "complete": self.summary.complete,
            "percentiles": self.percentiles or None,
            "series_source": self.series_source,
            "sampling_rate": options.sampling_rate if options.detailed else None,
            "parse_error": self.error,
        }


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def progress_series(stderr: str, interval_s: int) -> list[SeriesPoint]:
    """Fallback when the -l log is empty (SIGINT, crash): the `progress:` lines."""
    points: list[SeriesPoint] = []
    for line in stderr.splitlines():
        p = parse_bench_progress(line)
        if p is None:
            continue
        points.append(
            SeriesPoint(
                t_s=max(round(p.t) - interval_s, 0),
                tx=round(p.tps * interval_s),
                tps=p.tps,
                lat_avg_ms=p.lat_ms,
                lat_min_ms=None,
                lat_max_ms=None,
                lat_std_ms=p.stddev_ms,
                lag_ms=p.lag_ms,
                failed=p.failed,
                retried=p.retried,
                skipped=p.skipped,
            )
        )
    return points


def build_report(run_dir: Path, options: ReportOptions) -> RunReport:
    """Parse stdout, stderr and the -l logs; never raises for a malformed file."""
    stdout = _read(run_dir / "stdout.log")
    stderr = _read(run_dir / "stderr.log")
    report = RunReport(summary=parse_summary(stdout, stderr))
    try:
        files = log_files(run_dir)
        if options.detailed:
            tx = parse_tx_logs(
                files, with_lag=options.with_lag, sampling_rate=options.sampling_rate
            )
            report.series, report.series_source = tx.series, "transactions"
            report.histogram, report.percentiles = tx.histogram, tx.percentiles
            gzip_logs(files)
        else:
            report.series, report.series_source = parse_agg_logs(files), "aggregate"
    except (OSError, ValueError, EOFError) as exc:
        log.warning("run log parse failed", extra={"run_dir": str(run_dir), "error": str(exc)})
        report.error = f"Не удалось разобрать лог -l: {exc}"
        report.series = []
    if not report.series:
        report.series = progress_series(stderr, options.progress_interval_s)
        report.series_source = "progress" if report.series else None
    return report


def abort_reason(stderr_lines: list[str]) -> str | None:
    """The first «client N aborted in command …» line: why pgbench stopped early."""
    return next((line for line in stderr_lines if _ABORT_MARK in line), None)

"""Parsers of the report on real pgbench 18 output against PostgreSQL 13 and 18."""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import pytest

from app.core.parsers.agg_log import log_files, parse_agg_logs
from app.core.parsers.statements import Columns, parse_header, parse_row
from app.core.parsers.summary import Summary, parse_summary
from app.core.parsers.tx_log import (
    HistBucket,
    bucket_index,
    bucket_upper_ms,
    gzip_logs,
    parse_tx_logs,
    percentile,
)
from app.core.report import ReportOptions, abort_reason, build_report, progress_series
from tests.conftest import FIXTURES

COMPLETE = [
    "mixed-pg13",
    "mixed-pg18",
    "failures-pg13",
    "failures-pg18",
    "transactions-pg18",
    "rate-pg18",
    "detailed-pg18",
    "detailed-failures-pg13",
    "sampled-pg18",
    "aborted-detailed-pg18",
]
AGGREGATE = ["mixed-pg13", "mixed-pg18", "failures-pg13", "failures-pg18", "rate-pg18"]


def summary_of(case: str) -> Summary:
    d = FIXTURES / case
    return parse_summary((d / "stdout.log").read_text(), (d / "stderr.log").read_text())


def stdout_of(case: str) -> str:
    return (FIXTURES / case / "stdout.log").read_text()


# --- summary -------------------------------------------------------------------------------


@pytest.mark.parametrize("case", COMPLETE)
def test_summary_matches_pgbench_to_the_last_digit(case: str) -> None:
    """Every parsed number, printed back in pgbench's own format, is a line of its output."""
    s = summary_of(case)
    out = stdout_of(case).splitlines()
    assert s.complete
    assert f"tps = {s.tps:f} (without initial connection time)" in out
    assert f"latency average = {s.latency_avg_ms:.3f} ms" in out
    assert f"latency stddev = {s.latency_stddev_ms:.3f} ms" in out
    assert f"initial connection time = {s.initial_connection_ms:.3f} ms" in out
    assert f"number of failed transactions: {s.failed} ({s.failed_pct:.3f}%)" in out
    processed = f"number of transactions actually processed: {s.processed}"
    if s.processed_target is not None:
        processed += f"/{s.processed_target}"
    assert processed in out
    for script in s.scripts:
        for st in script.statements:
            assert any(
                line.startswith(f"   {st.latency_ms:11.3f}  {st.failures:10d} {st.command}")
                for line in out
            )
    if len(s.scripts) > 1:
        for script in s.scripts:
            assert f" - latency average = {script.latency_avg_ms:.3f} ms" in out
            assert (
                f" - number of transactions actually processed: {script.processed} "
                f"(tps = {script.tps:f})"
            ) in out


@pytest.mark.parametrize("server", ["pg13", "pg18"])
def test_summary_of_two_weighted_scripts_with_threads(server: str) -> None:
    s = summary_of(f"mixed-{server}")
    assert (s.clients, s.threads, s.duration_s, s.query_mode) == (4, 2, 5, "prepared")
    assert s.pgbench_version == "18.6"
    assert s.server_version == ("13.23" if server == "pg13" else None)  # same version: not printed
    assert s.transaction_type == "multiple scripts"
    tpcb, hot = s.scripts
    assert (tpcb.index, tpcb.name, tpcb.weight, tpcb.weight_pct) == (
        1,
        "<builtin: TPC-B (sort of)>",
        1,
        25.0,
    )
    assert (hot.name, hot.weight, hot.weight_pct) == ("hot.sql", 3, 75.0)
    assert tpcb.processed is not None and hot.processed is not None and s.processed is not None
    # pgbench's per-script counters may miss a few transactions of the total; shown as printed.
    assert abs(tpcb.processed + hot.processed - s.processed) <= s.processed * 0.001
    assert tpcb.share_pct is not None and hot.share_pct is not None
    assert round(tpcb.share_pct + hot.share_pct) == 100
    assert [st.command.split()[0] for st in tpcb.statements if not st.is_meta] == [
        "BEGIN;",
        "UPDATE",
        "SELECT",
        "UPDATE",
        "UPDATE",
        "INSERT",
        "END;",
    ]
    assert [st.idx for st in hot.statements] == [0, 1, 2, 3]
    assert all(st.script == 2 for st in hot.statements)


@pytest.mark.parametrize("server", ["pg13", "pg18"])
def test_summary_counts_serialization_failures(server: str) -> None:
    s = summary_of(f"failures-{server}")
    assert s.failed is not None and s.failed > 0
    assert s.failed == s.serialization_failures
    assert s.deadlock_failures == 0
    assert f"number of serialization failures: {s.failed} ({s.failed_pct:.3f}%)" in stdout_of(
        f"failures-{server}"
    )
    (script,) = s.scripts
    # One script: its block is the totals, statements carry the failures column.
    assert (script.name, script.processed, script.share_pct) == ("serial.sql", s.processed, 100.0)
    update = next(st for st in script.statements if st.command.startswith("UPDATE"))
    assert update.failures is not None and update.failures > 0


def test_summary_of_rate_and_latency_limit() -> None:
    s = summary_of("rate-pg18")
    out = stdout_of("rate-pg18")
    assert s.latency_limit_ms == 5.0
    assert (
        f"number of transactions above the 5.0 ms latency limit: {s.above_limit}/"
        f"{s.processed} ({s.above_limit_pct:.3f}%)"
    ) in out
    assert f"rate limit schedule lag: avg {s.lag_avg_ms:.3f} (max {s.lag_max_ms:.3f}) ms" in out
    assert s.skipped is not None
    assert f"number of transactions skipped: {s.skipped} ({s.skipped_pct:.3f}%)" in out


def test_summary_of_transactions_mode() -> None:
    s = summary_of("transactions-pg18")
    assert (s.transactions_per_client, s.processed, s.processed_target) == (300, 600, 600)
    assert s.duration_s is None


def test_aborted_clients_are_flagged() -> None:
    s = summary_of("aborted-detailed-pg18")
    assert s.aborted and s.complete


@pytest.mark.parametrize("case", ["cancelled-pg18", "aborted-pg13", "aborted-pg18"])
def test_no_summary_after_sigint_or_crash(case: str) -> None:
    s = summary_of(case)
    assert not s.complete
    assert s.scripts == []
    assert s.pgbench_version == "18.6"


def test_summary_with_retries_and_reconnects() -> None:
    text = "\n".join(
        [
            "maximum number of tries: 3",
            "number of transactions actually processed: 10",
            "number of transactions retried: 2 (20.000%)",
            "total number of retries: 5",
            "latency average = 1.500 ms (including failures)",
            "average connection time = 0.500 ms",
            "tps = 12.000000 (including reconnection times)",
            "statement latencies in milliseconds, failures and retries:",
            "         0.500           1           4 SELECT 1;",
            "not a row",
        ]
    )
    s = parse_summary(text)
    assert (s.max_tries, s.retried, s.retried_pct, s.retries) == (3, 2, 20.0, 5)
    assert (s.latency_avg_ms, s.tps) == (1.5, 12.0)
    (st,) = s.scripts[0].statements
    assert (st.failures, st.retries, st.command) == (1, 4, "SELECT 1;")


def test_statement_rows() -> None:
    both = parse_header("statement latencies in milliseconds, failures and retries:")
    assert both == Columns(failures=True, retries=True)
    assert parse_header(" - statement latencies in milliseconds and failures:") == Columns(
        failures=True, retries=False
    )
    assert parse_header("latency average = 1 ms") is None
    none = Columns(failures=False, retries=False)
    row = parse_row("         0.123 \\set x 1", none, 1, 0)
    assert row is not None and row.is_meta and row.failures is None
    assert parse_row("   0.1 x SELECT", both, 1, 0) is None
    assert parse_row("SELECT", both, 1, 0) is None


# --- aggregate log -------------------------------------------------------------------------


@pytest.mark.parametrize("case", AGGREGATE)
def test_aggregate_log_merges_thread_files(case: str) -> None:
    files = log_files(FIXTURES / case)
    assert len(files) == 2  # -j 2: pgbench_log.<pid> and pgbench_log.<pid>.1
    merged = parse_agg_logs(files)
    per_file = [parse_agg_logs([f]) for f in files]
    assert merged[0].t_s == 0
    assert [p.t_s for p in merged] == list(range(len(merged)))
    assert sum(p.tx for p in merged) == sum(p.tx for f in per_file for p in f)
    assert sum(p.failed for p in merged) == sum(p.failed for f in per_file for p in f)
    # min and max over all files
    first = max(per_file, key=len)
    assert all(
        m.lat_max_ms is not None and o.lat_max_ms is not None and m.lat_max_ms >= o.lat_max_ms
        for m, o in zip(merged[-len(first) :], first, strict=True)
    )
    # pgbench does not write the last, incomplete interval: the log misses under a second.
    s = summary_of(case)
    assert s.processed is not None
    logged = sum(p.tx for p in merged)
    assert 0 <= s.processed - logged <= max(p.tx for p in merged)


@pytest.mark.parametrize("server", ["pg13", "pg18"])
def test_aggregate_log_has_failures_per_second(server: str) -> None:
    series = parse_agg_logs(log_files(FIXTURES / f"failures-{server}"))
    s = summary_of(f"failures-{server}")
    assert s.failed is not None
    assert 0 <= s.failed - sum(p.failed for p in series) <= max(p.failed for p in series)
    assert all(p.lag_ms is None for p in series)


def test_aggregate_log_values() -> None:
    series = parse_agg_logs(log_files(FIXTURES / "rate-pg18"))
    assert all(p.lag_ms is not None for p in series if p.tx)
    p = series[1]
    assert p.tps == p.tx
    assert p.lat_min_ms is not None and p.lat_avg_ms is not None and p.lat_max_ms is not None
    assert p.lat_min_ms <= p.lat_avg_ms <= p.lat_max_ms
    assert p.lat_std_ms is not None and p.lat_std_ms > 0


def test_aggregate_log_edge_cases(tmp_path: Path) -> None:
    log = tmp_path / "pgbench_log.1"
    log.write_text(
        "garbage\n100 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n101 x 1 1 1 1\n102 2 3000 5000000 1000 2000\n"
    )
    (tmp_path / "pgbench_log.2").symlink_to(log)
    assert log_files(tmp_path) == [log]
    empty, point = parse_agg_logs([log])
    assert (empty.t_s, empty.tx, empty.lat_avg_ms, empty.lat_min_ms) == (0, 0, None, None)
    assert (point.t_s, point.tx, point.lat_avg_ms, point.lat_min_ms, point.lat_max_ms) == (
        2,
        2,
        1.5,
        1.0,
        2.0,
    )
    assert point.lat_std_ms == 0.5
    assert parse_agg_logs([]) == []


# --- per-transaction log -------------------------------------------------------------------


def test_transaction_log_counts_match_summary() -> None:
    result = parse_tx_logs(log_files(FIXTURES / "detailed-pg18"))
    s = summary_of("detailed-pg18")
    assert result.transactions == s.processed == sum(p.tx for p in result.series)
    assert result.failed == 0
    assert sum(count for _, count in result.histogram) == result.transactions
    avg = sum((p.lat_avg_ms or 0) * p.tx for p in result.series) / result.transactions
    assert s.latency_avg_ms is not None
    assert abs(avg - s.latency_avg_ms) < 0.001
    p50, p95, p99 = (result.percentiles[k] for k in ("p50", "p95", "p99"))
    assert p50 <= p95 <= p99
    uppers = [u for u, _ in result.histogram]
    assert uppers == sorted(uppers)


def test_transaction_log_failures_on_pg13() -> None:
    result = parse_tx_logs(log_files(FIXTURES / "detailed-failures-pg13"))
    s = summary_of("detailed-failures-pg13")
    assert (result.transactions, result.failed) == (s.processed, s.failed)
    assert sum(p.failed for p in result.series) == s.failed


def test_sampled_log_is_scaled_back() -> None:
    result = parse_tx_logs(log_files(FIXTURES / "sampled-pg18"), sampling_rate=0.1)
    s = summary_of("sampled-pg18")
    assert s.processed is not None
    assert result.transactions < s.processed / 5
    assert abs(sum(p.tx for p in result.series) - s.processed) < 0.05 * s.processed


def test_transaction_log_lag_skipped_and_gzip(tmp_path: Path) -> None:
    log = tmp_path / "pgbench_log.7"
    log.write_text(
        "0 1 1500 0 1000 10 200\n"
        "0 2 skipped 0 1000 20 0\n"
        "0 3 serialization 0 1001 5 0\n"
        "0 4 2500 0 1001 9 400\n"
        "bad line\n"
        "0 5 oops 0 1001 9 0\n"
    )
    plain = parse_tx_logs([log], with_lag=True)
    (gz,) = gzip_logs([log])
    assert gz.name == "pgbench_log.7.gz" and not log.exists()
    assert gzip.decompress(gz.read_bytes()).startswith(b"0 1 1500")
    assert gzip_logs([gz]) == [gz]
    again = parse_tx_logs(log_files(tmp_path), with_lag=True)
    assert again == plain
    first, second = plain.series
    assert (first.tx, first.lag_ms, first.lat_avg_ms) == (1, 0.2, 1.5)
    assert (second.tx, second.failed, second.lag_ms) == (1, 1, 0.4)
    assert (plain.skipped, plain.failed, plain.transactions) == (1, 1, 2)


def test_percentiles_and_buckets() -> None:
    assert bucket_index(0) == -1 and bucket_upper_ms(-1) == 0.001
    assert bucket_index(1) == 0
    assert bucket_index(100) < bucket_index(102)  # 1 % buckets
    assert bucket_upper_ms(bucket_index(5000)) > 5.0
    hist = {bucket_index(v): HistBucket(1, v, v) for v in range(1, 101)}
    assert percentile(hist, 100, 0.5) == 0.05
    assert percentile(hist, 100, 0.99) == 0.099
    assert percentile({}, 0, 0.5) is None
    wide = {10: HistBucket(4, 100, 400)}
    assert percentile(wide, 4, 0.5) == 0.25


# --- whole report --------------------------------------------------------------------------


def copy_case(case: str, tmp_path: Path) -> Path:
    target = tmp_path / case
    shutil.copytree(FIXTURES / case, target)
    return target


def test_report_from_aggregate_log(tmp_path: Path) -> None:
    run_dir = copy_case("mixed-pg13", tmp_path)
    options = ReportOptions(scripts=["tpcb-like", "select_hot"])
    report = build_report(run_dir, options)
    assert report.series_source == "aggregate" and report.series
    assert report.histogram == [] and report.percentiles == {}
    names = {name for name, _ in report.statements(options.scripts)}
    assert names == {"tpcb-like", "select_hot"}
    data = report.summary_json(options)
    assert data["complete"] is True and data["percentiles"] is None
    assert [s["scenario"] for s in data["pgbench"]["scripts"]] == ["tpcb-like", "select_hot"]
    assert "statements" not in data["pgbench"]["scripts"][0]
    # names unknown (older run): pgbench's own description is kept
    assert report.statements([])[0][0] == "<builtin: TPC-B (sort of)>"


def test_report_detailed_mode_gzips_logs(tmp_path: Path) -> None:
    run_dir = copy_case("detailed-pg18", tmp_path)
    report = build_report(run_dir, ReportOptions(detailed=True, scripts=["simple-update"]))
    assert report.series_source == "transactions"
    assert set(report.percentiles) == {"p50", "p95", "p99"}
    assert report.histogram
    assert all(p.name.endswith(".gz") for p in log_files(run_dir))


def test_report_falls_back_to_progress_lines(tmp_path: Path) -> None:
    run_dir = copy_case("cancelled-pg18", tmp_path)
    report = build_report(run_dir, ReportOptions())
    assert report.series_source == "progress"
    (point,) = report.series
    assert f"progress: 1.0 s, {point.tps:.1f} tps" in (run_dir / "stderr.log").read_text()
    assert (point.t_s, point.tx, point.failed) == (0, round(point.tps), 0)
    assert report.summary_json(ReportOptions())["complete"] is False


def test_report_without_any_series(tmp_path: Path) -> None:
    run_dir = copy_case("transactions-pg18", tmp_path)  # 14 ms: no interval, no progress line
    report = build_report(run_dir, ReportOptions())
    assert report.series == [] and report.series_source is None
    assert build_report(tmp_path / "missing", ReportOptions()).summary.complete is False


def test_report_survives_a_broken_log(tmp_path: Path) -> None:
    run_dir = copy_case("cancelled-pg18", tmp_path)
    (run_dir / "pgbench_log.1.gz").write_bytes(b"not gzip")
    report = build_report(run_dir, ReportOptions(detailed=True))
    assert report.error is not None and "лог -l" in report.error
    assert report.series_source == "progress"


def test_progress_series_and_abort_reason() -> None:
    stderr = (FIXTURES / "aborted-pg18" / "stderr.log").read_text().splitlines()
    reason = abort_reason(stderr)
    assert reason is not None and "division by zero" in reason
    assert abort_reason(["pgbench: error: unexpected error status: 4"]) is None
    points = progress_series(
        "progress: 2.0 s, 10.0 tps, lat 1.000 ms stddev NaN, 3 failed, lag 0.500 ms\n", 2
    )
    assert (points[0].t_s, points[0].tx, points[0].lat_std_ms, points[0].lag_ms) == (
        0,
        20,
        None,
        0.5,
    )

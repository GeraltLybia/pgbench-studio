from __future__ import annotations

import pytest

from app.config import LimitsSettings
from app.core.command import (
    BenchOptions,
    ScenarioRef,
    build_bench_argv,
    build_dry_argv,
    render_command,
    script_file_names,
)
from app.core.limits import LoadShape, agent_cpu_count, check_limits

LIMITS = LimitsSettings()  # reserve 5, max 4 h, 100 M transactions


def codes(shape: LoadShape, **kwargs: object) -> dict[str, str]:
    params: dict[str, object] = {
        "free_connections": 105,
        "cpu_count": 8,
        "server_major": 16,
        "pgbench_major": 18,
    }
    params.update(kwargs)
    return {f.code: f.level for f in check_limits(shape, LIMITS, **params)}  # type: ignore[arg-type]


def dur(clients: int = 8, threads: int = 4, duration_s: int = 300, **kw: object) -> LoadShape:
    return LoadShape(mode="duration", clients=clients, threads=threads, duration_s=duration_s, **kw)  # type: ignore[arg-type]


# free 105 - reserve 5 = 100 available; 80 % = 80
@pytest.mark.parametrize(
    ("clients", "expected"),
    [
        (80, {}),
        (81, {"clients_near_free": "warning"}),
        (100, {"clients_near_free": "warning"}),
        (101, {"clients_over_free": "error"}),
    ],
)
def test_clients_vs_free_connections(clients: int, expected: dict[str, str]) -> None:
    assert codes(dur(clients=clients, threads=1)) == expected


def test_clients_without_connection_facts() -> None:
    assert codes(dur(clients=10_000, threads=1), free_connections=None) == {}


@pytest.mark.parametrize(
    ("clients", "threads", "cpus", "expected"),
    [
        (8, 8, 8, {}),
        (8, 9, 16, {"threads_over_clients": "error"}),
        (16, 9, 8, {"threads_over_cores": "error"}),
    ],
)
def test_threads(clients: int, threads: int, cpus: int, expected: dict[str, str]) -> None:
    assert codes(dur(clients=clients, threads=threads), cpu_count=cpus) == expected


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (9, {"duration_too_short": "error"}),
        (10, {}),
        (3600, {}),
        (3601, {"duration_long": "warning"}),
        (14400, {"duration_long": "warning"}),
        (14401, {"duration_over_max": "error"}),
    ],
)
def test_duration(duration: int, expected: dict[str, str]) -> None:
    assert codes(dur(duration_s=duration)) == expected


@pytest.mark.parametrize(
    ("clients", "tx", "expected"),
    [
        (10, 10_000_000, {}),
        (10, 10_000_001, {"transactions_over_max": "error"}),
        (1, 0, {"transactions_missing": "error"}),
    ],
)
def test_transactions(clients: int, tx: int, expected: dict[str, str]) -> None:
    shape = LoadShape(mode="transactions", clients=clients, threads=1, transactions=tx)
    assert codes(shape) == expected


def test_rate_and_latency_must_be_positive() -> None:
    found = codes(dur(rate_tps=0, latency_limit_ms=-1))
    assert found == {"rate_not_positive": "error", "latency_limit_not_positive": "error"}
    assert codes(dur(rate_tps=0.5, latency_limit_ms=0.1)) == {}


@pytest.mark.parametrize(("major", "warn"), [(12, True), (13, False), (18, False), (19, True)])
def test_server_version_warning(major: int, warn: bool) -> None:
    assert ("server_version" in codes(dur(), server_major=major)) is warn


def test_rule_id_and_cpu_count() -> None:
    finding = check_limits(
        dur(duration_s=5),
        LIMITS,
        free_connections=None,
        cpu_count=4,
        server_major=None,
        pgbench_major=None,
    )[0]
    assert finding.rule_id == "limits.duration_too_short"
    assert agent_cpu_count() >= 1


# --- argv ----------------------------------------------------------------------------------

MOCKUP = BenchOptions(
    mode="duration",
    duration_s=300,
    clients=32,
    threads=8,
    protocol="prepared",
    scenarios=[ScenarioRef("builtin", "tpcb-like", 1), ScenarioRef("file", "select_hot.sql", 3)],
)


def test_bench_argv_matches_the_mockup() -> None:
    assert build_bench_argv("pgbench", MOCKUP) == [
        "pgbench",
        "-c",
        "32",
        "-j",
        "8",
        "-T",
        "300",
        "-M",
        "prepared",
        "-P",
        "1",
        "-r",
        "-l",
        "--log-prefix=pgbench_log",
        "--failures-detailed",
        "--aggregate-interval=1",
        "-b",
        "tpcb-like@1",
        "-f",
        "select_hot.sql@3",
    ]


def test_bench_argv_all_options() -> None:
    options = BenchOptions(
        mode="transactions",
        transactions=1000,
        clients=4,
        threads=2,
        protocol="simple",
        scenarios=[ScenarioRef("file", "a.sql", 1)],
        rate_tps=500.0,
        latency_limit_ms=12.5,
        vacuum=False,
        variables=[("x", "1"), ("name", "a b")],
        detailed_log=True,
        sampling_rate=0.1,
        progress_interval_s=5,
    )
    assert build_bench_argv("/usr/bin/pgbench", options) == [
        "/usr/bin/pgbench",
        "-c",
        "4",
        "-j",
        "2",
        "-t",
        "1000",
        "-M",
        "simple",
        "-R",
        "500",
        "--latency-limit=12.5",
        "-n",
        "-D",
        "x=1",
        "-D",
        "name=a b",
        "-P",
        "5",
        "-r",
        "-l",
        "--log-prefix=pgbench_log",
        "--sampling-rate=0.1",
        "-f",
        "a.sql@1",
    ]


def test_detailed_log_without_sampling_has_no_aggregation() -> None:
    options = BenchOptions(**{**MOCKUP.__dict__, "detailed_log": True})
    argv = build_bench_argv("pgbench", options)
    assert not any(
        a.startswith(("--aggregate-interval", "--sampling-rate", "--failures-detailed"))
        for a in argv
    )


def test_dry_argv() -> None:
    options = BenchOptions(**{**MOCKUP.__dict__, "variables": [("x", "1")]})
    assert build_dry_argv("pgbench", options) == [
        "pgbench",
        "-c",
        "1",
        "-j",
        "1",
        "-t",
        "1",
        "-n",
        "-M",
        "prepared",
        "-D",
        "x=1",
        "-r",
        "-b",
        "tpcb-like@1",
        "-f",
        "select_hot.sql@3",
    ]


def test_script_file_names_are_safe_and_unique() -> None:
    assert script_file_names(
        ["select_hot.sql", "select_hot.sql", "../etc/passwd", "-x", "Пример"]
    ) == [
        "select_hot.sql",
        "select_hot-2.sql",
        "etc_passwd.sql",
        "x.sql",
        "script.sql",
    ]


def test_render_command_masks_password() -> None:
    text = render_command(
        ["pgbench", "-D", "a=b c"], {"PGHOST": "db", "PGPASSWORD": "s3cr3t", "PATH": "/x"}
    )
    assert text == "PGHOST=db PGPASSWORD=•••••• pgbench -D 'a=b c'"
    assert "s3cr3t" not in text

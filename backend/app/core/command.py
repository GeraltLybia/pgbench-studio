"""pgbench argv builders. Connection parameters and the password travel via env, never argv."""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

# Rough on-disk size of one scale unit (tables + indexes) at fillfactor 100.
BYTES_PER_SCALE = 15 * 1024**2
LARGE_INIT_BYTES = 50 * 1024**3


@dataclass(frozen=True)
class InitOptions:
    scale: int
    fillfactor: int
    foreign_keys: bool
    unlogged: bool


def build_init_argv(binary: str, options: InitOptions) -> list[str]:
    argv = [binary, "-i", "-s", str(options.scale), "-F", str(options.fillfactor)]
    if options.foreign_keys:
        argv.append("--foreign-keys")
    if options.unlogged:
        argv.append("--unlogged-tables")
    return argv


def estimate_init_bytes(scale: int, fillfactor: int) -> int:
    """Approximate data size after `pgbench -i`; lower fillfactor leaves free space in pages."""
    return int(scale * BYTES_PER_SCALE * 100 / fillfactor)


# pgbench writes logs next to its cwd, which is the run directory.
LOG_PREFIX = "pgbench_log"
MASK = "••••••"

_UNSAFE_FILE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True)
class ScenarioRef:
    """A builtin (-b name@w) or a script file written into the run directory (-f file@w)."""

    kind: Literal["builtin", "file"]
    name: str
    weight: int


@dataclass(frozen=True)
class BenchOptions:
    mode: Literal["duration", "transactions"]
    clients: int
    threads: int
    protocol: Literal["simple", "extended", "prepared"]
    scenarios: list[ScenarioRef]
    duration_s: int | None = None
    transactions: int | None = None
    rate_tps: float | None = None
    latency_limit_ms: float | None = None
    vacuum: bool = True
    variables: list[tuple[str, str]] = field(default_factory=list)
    detailed_log: bool = False
    sampling_rate: float | None = None
    progress_interval_s: int = 1


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def script_file_names(names: list[str]) -> list[str]:
    """Safe, unique file names chosen by the backend (never taken verbatim from input)."""
    result: list[str] = []
    for raw in names:
        base = _UNSAFE_FILE_CHARS.sub("_", raw).lstrip("._-")[:60] or "script"
        if not base.endswith(".sql"):
            base += ".sql"
        stem, candidate, n = base[:-4], base, 2
        while candidate in result:
            candidate = f"{stem}-{n}.sql"
            n += 1
        result.append(candidate)
    return result


def _scenario_args(scenarios: list[ScenarioRef]) -> list[str]:
    argv: list[str] = []
    for ref in scenarios:
        argv += ["-b" if ref.kind == "builtin" else "-f", f"{ref.name}@{ref.weight}"]
    return argv


def build_bench_argv(binary: str, options: BenchOptions) -> list[str]:
    argv = [binary, "-c", str(options.clients), "-j", str(options.threads)]
    if options.mode == "duration":
        argv += ["-T", str(options.duration_s)]
    else:
        argv += ["-t", str(options.transactions)]
    argv += ["-M", options.protocol]
    if options.rate_tps is not None:
        argv += ["-R", _num(options.rate_tps)]
    if options.latency_limit_ms is not None:
        argv += [f"--latency-limit={_num(options.latency_limit_ms)}"]
    if not options.vacuum:
        argv.append("-n")
    for name, value in options.variables:
        argv += ["-D", f"{name}={value}"]
    argv += ["-P", str(options.progress_interval_s), "-r", "-l", f"--log-prefix={LOG_PREFIX}"]
    if options.detailed_log:
        if options.sampling_rate is not None:
            argv.append(f"--sampling-rate={_num(options.sampling_rate)}")
    else:
        # Failures reach the aggregate log only with --failures-detailed (pgbench 18).
        # Not in detailed mode: there a failure is logged as `failed`, and with the flag
        # pgbench 18.6 exits on a client aborted by an SQL error.
        argv += ["--failures-detailed", "--aggregate-interval=1"]
    return argv + _scenario_args(options.scenarios)


def build_dry_argv(binary: str, options: BenchOptions) -> list[str]:
    """Trial run: one client, one transaction, no vacuum; same scripts and variables."""
    argv = [binary, "-c", "1", "-j", "1", "-t", "1", "-n", "-M", options.protocol]
    for name, value in options.variables:
        argv += ["-D", f"{name}={value}"]
    return [*argv, "-r", *_scenario_args(options.scenarios)]


def render_command(argv: list[str], env: Mapping[str, str]) -> str:
    """Shell-style preview: PG* variables (password masked) and the exact argv."""
    shown = [
        f"{k}={MASK if k == 'PGPASSWORD' else shlex.quote(v)}"
        for k, v in env.items()
        if k.startswith("PG")
    ]
    prefix = " ".join(shown)
    command = shlex.join(argv)
    return f"{prefix} {command}" if prefix else command

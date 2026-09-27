"""pgbench argv builders. Connection parameters and the password travel via env, never argv."""

from __future__ import annotations

from dataclasses import dataclass

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

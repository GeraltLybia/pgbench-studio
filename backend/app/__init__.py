"""pgbench studio backend."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pgbench-studio")
except PackageNotFoundError:  # pragma: no cover - running from a source tree without install
    __version__ = "0.0.0"

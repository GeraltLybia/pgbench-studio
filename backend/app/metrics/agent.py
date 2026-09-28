"""Resources of the load agent (this machine) sampled with psutil. No DB server monitoring."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class AgentSample:
    cpu_pct: float
    ram_pct: float
    ram_used_bytes: int
    ram_total_bytes: int


def sample() -> AgentSample:
    memory = psutil.virtual_memory()
    return AgentSample(
        cpu_pct=psutil.cpu_percent(interval=None),
        ram_pct=memory.percent,
        ram_used_bytes=memory.total - memory.available,
        ram_total_bytes=memory.total,
    )


class CpuWarning:
    """Fires once when CPU goes above the threshold; re-arms after it drops back below."""

    def __init__(self, threshold_pct: int) -> None:
        self.threshold_pct = threshold_pct
        self._above = False

    def check(self, cpu_pct: float) -> bool:
        if cpu_pct > self.threshold_pct and not self._above:
            self._above = True
            return True
        if cpu_pct <= self.threshold_pct:
            self._above = False
        return False


async def run_sampler(
    interval_s: float,
    on_sample: Callable[[AgentSample], Awaitable[None]],
    sampler: Callable[[], AgentSample] = sample,
) -> None:
    """Sample every `interval_s` until cancelled."""
    psutil.cpu_percent(interval=None)  # the first reading is meaningless; prime it
    while True:
        await asyncio.sleep(interval_s)
        with contextlib.suppress(Exception):
            await on_sample(sampler())

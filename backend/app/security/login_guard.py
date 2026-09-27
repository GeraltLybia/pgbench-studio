"""Failed login accounting per client IP (per-login accounting lives in the users table)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class _IpState:
    failures: int = 0
    locked_until: datetime | None = None


class IpLoginGuard:
    """In-memory counter of consecutive failed logins per real client IP."""

    def __init__(self, max_failures: int, lockout: timedelta) -> None:
        self.max_failures = max_failures
        self.lockout = lockout
        self._state: dict[str, _IpState] = {}

    def locked_until(self, ip: str, now: datetime) -> datetime | None:
        state = self._state.get(ip)
        if state is None or state.locked_until is None:
            return None
        if state.locked_until <= now:
            del self._state[ip]
            return None
        return state.locked_until

    def attempts_left(self, ip: str) -> int:
        state = self._state.get(ip)
        return self.max_failures - (state.failures if state else 0)

    def register_failure(self, ip: str, now: datetime) -> None:
        state = self._state.setdefault(ip, _IpState())
        state.failures += 1
        if state.failures >= self.max_failures:
            state.locked_until = now + self.lockout

    def register_success(self, ip: str) -> None:
        self._state.pop(ip, None)

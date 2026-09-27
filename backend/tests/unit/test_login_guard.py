from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.security.login_guard import IpLoginGuard

NOW = datetime(2026, 9, 27, tzinfo=UTC)


def test_locks_after_max_failures_and_expires() -> None:
    guard = IpLoginGuard(3, timedelta(minutes=5))
    for _ in range(2):
        guard.register_failure("1.1.1.1", NOW)
    assert guard.locked_until("1.1.1.1", NOW) is None
    assert guard.attempts_left("1.1.1.1") == 1
    guard.register_failure("1.1.1.1", NOW)
    assert guard.locked_until("1.1.1.1", NOW) == NOW + timedelta(minutes=5)
    assert guard.locked_until("2.2.2.2", NOW) is None
    later = NOW + timedelta(minutes=5)
    assert guard.locked_until("1.1.1.1", later) is None
    assert guard.attempts_left("1.1.1.1") == 3


def test_success_resets() -> None:
    guard = IpLoginGuard(3, timedelta(minutes=5))
    guard.register_failure("1.1.1.1", NOW)
    guard.register_success("1.1.1.1")
    assert guard.attempts_left("1.1.1.1") == 3

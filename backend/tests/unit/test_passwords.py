from __future__ import annotations

from app.security.passwords import (
    generate_temporary_password,
    hash_password,
    needs_rehash,
    verify_dummy,
    verify_password,
)


def test_hash_is_argon2id_and_verifies() -> None:
    hashed = hash_password("secret-1")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "secret-1")
    assert not verify_password(hashed, "secret-2")
    assert not needs_rehash(hashed)


def test_invalid_hash_does_not_raise() -> None:
    assert not verify_password("garbage", "secret")


def test_dummy_verify_runs() -> None:
    verify_dummy("anything")


def test_temporary_password() -> None:
    a, b = generate_temporary_password(), generate_temporary_password()
    assert len(a) == 14
    assert a.isalnum()
    assert a != b

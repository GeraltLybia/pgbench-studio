from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.core.command import (
    BYTES_PER_SCALE,
    LARGE_INIT_BYTES,
    InitOptions,
    build_init_argv,
    estimate_init_bytes,
)
from app.core.parsers.progress import parse_init_phase, parse_init_progress
from app.storage.crypto import DecryptionError, SecretBox


def test_init_argv() -> None:
    assert build_init_argv("pgbench", InitOptions(100, 100, False, False)) == [
        "pgbench",
        "-i",
        "-s",
        "100",
        "-F",
        "100",
    ]
    assert build_init_argv("/usr/bin/pgbench", InitOptions(10, 90, True, True)) == [
        "/usr/bin/pgbench",
        "-i",
        "-s",
        "10",
        "-F",
        "90",
        "--foreign-keys",
        "--unlogged-tables",
    ]


def test_estimate_matches_mockup_and_fillfactor() -> None:
    assert estimate_init_bytes(100, 100) == 100 * BYTES_PER_SCALE  # ≈ 1.5 GB on the mockup
    assert estimate_init_bytes(100, 50) == 2 * estimate_init_bytes(100, 100)
    assert estimate_init_bytes(3500, 100) > LARGE_INIT_BYTES
    assert estimate_init_bytes(3400, 100) < LARGE_INIT_BYTES


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            "100000 of 10000000 tuples (1%) of pgbench_accounts done"
            " (elapsed 0.05 s, remaining 4.51 s)",
            (100000, 10000000, 1.0, 0.05, 4.51),
        ),
        (
            "100000 of 1000000 tuples (10%) done (elapsed 0.06 s, remaining 0.54 s)",
            (100000, 1000000, 10.0, 0.06, 0.54),
        ),
        ("5 of 10 tuples (50%) done", (5, 10, 50.0, None, None)),
        ("0 of 0 tuples (100%) done", (0, 0, 100.0, None, None)),
    ],
)
def test_parse_init_progress(line: str, expected: tuple[object, ...]) -> None:
    p = parse_init_progress(line)
    assert p is not None
    assert (p.done, p.total, p.pct, p.elapsed_s, p.remaining_s) == expected


def test_parse_init_progress_ignores_other_lines() -> None:
    assert parse_init_progress("creating tables...") is None
    assert parse_init_progress("progress: 5.0 s, 100.0 tps") is None


def test_parse_init_phase() -> None:
    assert parse_init_phase("creating tables...") == "Создание таблиц"
    assert parse_init_phase("generating data (server-side)...") == "Генерация данных"
    assert parse_init_phase("creating foreign keys...") == "Внешние ключи"
    assert parse_init_phase("done in 1.2 s (drop tables 0.0 s)") == "Готово"
    assert parse_init_phase("100 of 200 tuples (50%) done") is None


def test_secret_box_roundtrip_and_wrong_key() -> None:
    box = SecretBox(Fernet.generate_key())
    token = box.encrypt("p@ss")
    assert token != "p@ss"
    assert box.decrypt(token) == "p@ss"
    with pytest.raises(DecryptionError):
        SecretBox(Fernet.generate_key()).decrypt(token)

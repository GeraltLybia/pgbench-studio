from __future__ import annotations

from ipaddress import ip_network
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.config import ConfigError, Settings, config_path, load_settings, resolve_secret_key


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_match_document() -> None:
    s = Settings()
    assert s.server.port == 8000
    assert s.server.dev_mode is False
    assert s.auth.session_ttl_h == 12
    assert s.auth.cookie_secure is True
    assert s.auth.max_failed_logins == 5
    assert s.auth.lockout_min == 5
    assert s.pgbench.max_parallel_runs == 1
    assert s.agent.cpu_warning_percent == 85
    assert s.limits.max_duration_s == 14400
    assert s.limits.max_scale == 5000


def test_load_yaml(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "server:\n  port: 9000\n  trusted_proxies: [10.0.0.0/24]\nagent:\n  name: agent-x\n",
    )
    s = load_settings(path)
    assert s.server.port == 9000
    assert s.server.trusted_proxies == [ip_network("10.0.0.0/24")]
    assert s.agent.name == "agent-x"


def test_empty_file_gives_defaults(tmp_path: Path) -> None:
    assert load_settings(write(tmp_path, "")).server.port == 8000


def test_env_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write(tmp_path, "server:\n  port: 9000\n  dev_mode: false\n")
    monkeypatch.setenv("PGB_STUDIO_SERVER__PORT", "9100")
    monkeypatch.setenv("PGB_STUDIO_SERVER__DEV_MODE", "true")
    monkeypatch.setenv("PGB_STUDIO_LIMITS__MAX_SCALE", "7")
    s = load_settings(path)
    assert s.server.port == 9100
    assert s.server.dev_mode is True
    assert s.limits.max_scale == 7


def test_path_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write(tmp_path, "agent:\n  name: from-env\n")
    monkeypatch.setenv("PGB_STUDIO_CONFIG", str(path))
    assert config_path() == path
    assert load_settings().agent.name == "from-env"


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="не найден"):
        load_settings(tmp_path / "nope.yaml")


def test_invalid_yaml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="некорректный YAML"):
        load_settings(write(tmp_path, "server: [unclosed\n"))


def test_top_level_not_mapping(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="словарь секций"):
        load_settings(write(tmp_path, "- a\n- b\n"))


def test_validation_errors_are_readable(tmp_path: Path) -> None:
    path = write(tmp_path, "server:\n  port: abc\n  bogus: 1\nunknown: 2\n")
    with pytest.raises(ConfigError) as info:
        load_settings(path)
    message = str(info.value)
    assert str(path) in message
    assert "server.port" in message
    assert "'abc'" in message
    assert "server.bogus" in message
    assert "unknown" in message


def test_out_of_range_value(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"agent\.cpu_warning_percent"):
        load_settings(write(tmp_path, "agent:\n  cpu_warning_percent: 150\n"))


def test_insecure_cookie_requires_dev_mode(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cookie_secure"):
        load_settings(write(tmp_path, "auth:\n  cookie_secure: false\n"))
    s = load_settings(write(tmp_path, "server:\n  dev_mode: true\nauth:\n  cookie_secure: false\n"))
    assert s.auth.cookie_secure is False


def test_secret_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MY_KEY", raising=False)
    with pytest.raises(ConfigError, match="MY_KEY"):
        resolve_secret_key("MY_KEY")


def test_secret_key_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_KEY", "not-a-fernet-key")
    with pytest.raises(ConfigError, match="некорректен"):
        resolve_secret_key("MY_KEY")


def test_secret_key_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    key = Fernet.generate_key()
    monkeypatch.setenv("PGB_STUDIO_SECRET_KEY", key.decode())
    assert Settings().secret_key() == key

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import cli
from app.config import ConfigError, Settings
from app.main import create_app
from app.storage import repo
from app.storage.db import create_engine_for, make_sessionmaker


def test_startup_refuses_without_secret_key(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PGB_STUDIO_SECRET_KEY", raising=False)
    with pytest.raises(ConfigError), TestClient(create_app(settings)):
        pass


def test_no_admin_env_creates_nobody(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("PGB_STUDIO_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("PGB_STUDIO_ADMIN_USER", raising=False)
    with TestClient(create_app(settings), base_url="https://t") as client:

        async def count() -> int:
            async with client.app.state.sessionmaker() as db:  # type: ignore[attr-defined]
                return await repo.count_users(db)

        assert client.portal.call(count) == 0  # type: ignore[union-attr]
    assert "no users exist" in caplog.text


def write_config(tmp_path: Path, settings: Settings) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        json.dumps(
            {
                "storage": {
                    "sqlite_path": str(settings.storage.sqlite_path),
                    "runs_dir": str(settings.storage.runs_dir),
                },
                "pgbench": {"binary": settings.pgbench.binary},
            }
        )
    )
    return path


def test_gen_key(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["gen-key"]) == 0
    Fernet(capsys.readouterr().out.strip().encode())


def test_openapi_dump(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    assert cli.main(["openapi", "-o", str(out)]) == 0
    schema = json.loads(out.read_text())
    assert "/api/auth/login" in schema["paths"]


def test_openapi_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["openapi"]) == 0
    assert json.loads(capsys.readouterr().out)["info"]["title"] == "pgbench studio"


def test_serve_with_broken_config_exits_with_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "config.yaml"
    bad.write_text("server:\n  port: not-a-port\n")
    with pytest.raises(SystemExit) as info:
        cli.main(["--config", str(bad), "serve"])
    assert info.value.code == 2
    err = capsys.readouterr().err
    assert "server.port" in err


def test_serve_without_key_exits(
    tmp_path: Path,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("PGB_STUDIO_SECRET_KEY", raising=False)
    assert cli.main(["--config", str(write_config(tmp_path, settings)), "serve"]) == 2
    assert "PGB_STUDIO_SECRET_KEY" in capsys.readouterr().err


def test_serve_starts_uvicorn(
    tmp_path: Path, settings: Settings, secret_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(app: Any, **kwargs: Any) -> None:
        seen.update(kwargs, app=app)

    monkeypatch.setattr("uvicorn.run", fake_run)
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "172.28.0.10")
    assert cli.main(["--config", str(write_config(tmp_path, settings)), "serve"]) == 0
    assert seen["proxy_headers"] is True
    assert seen["forwarded_allow_ips"] == "172.28.0.10"
    assert seen["port"] == 8000


def test_reset_admin_creates_and_restores(
    tmp_path: Path,
    settings: Settings,
    capsys: pytest.CaptureFixture[str],
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = write_config(tmp_path, settings)
    assert cli.main(["--config", str(config), "users", "reset-admin", "--username", "boss"]) == 0
    first = capsys.readouterr().out.split("Временный пароль: ")[1].split()[0]

    monkeypatch.setenv("PGB_STUDIO_ADMIN_USER", "boss")
    assert cli.main(["--config", str(config), "users", "reset-admin"]) == 0
    second = capsys.readouterr().out.split("Временный пароль: ")[1].split()[0]
    assert first != second

    import asyncio

    from app.security.passwords import verify_password

    async def load() -> Any:
        engine = create_engine_for(settings.storage.sqlite_path)
        async with make_sessionmaker(engine)() as db:
            user = await repo.get_user_by_username(db, "boss")
        await engine.dispose()
        return user

    user = asyncio.run(load())
    assert user.role == "admin"
    assert user.must_change_password
    assert verify_password(user.password_hash, second)


def test_reset_admin_needs_username(
    tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PGB_STUDIO_ADMIN_USER", raising=False)
    config = write_config(tmp_path, settings)
    assert cli.main(["--config", str(config), "users", "reset-admin"]) == 2


def test_startup_explains_a_read_only_data_dir(
    make_settings: Callable[..., Settings], tmp_path: Path, secret_env: str
) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        settings = make_settings(
            storage={"sqlite_path": str(locked / "studio.db"), "runs_dir": str(locked / "runs")}
        )
        app = create_app(settings)
        with pytest.raises(ConfigError, match="chown 10001:10001"), TestClient(app):
            pass
    finally:
        locked.chmod(0o755)

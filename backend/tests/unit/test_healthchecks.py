from __future__ import annotations

import sqlite3
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.core import healthchecks as hc
from app.core.healthchecks import CheckResult, HealthService
from app.storage.db import head_revision, run_migrations
from tests.conftest import ADMIN, ADMIN_PASSWORD, Api

GB = 1024**3


def script(tmp_path: Path, body: str, name: str = "pgbench") -> str:
    path = tmp_path / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def result(status: hc.Status, required: bool = True) -> CheckResult:
    return CheckResult("x", "x", required, status, "")


def test_overall_status() -> None:
    assert hc.overall_status([result("ok"), result("ok", False)]) == "ok"
    assert hc.overall_status([result("ok"), result("warning")]) == "warning"
    assert hc.overall_status([result("ok"), result("fail", False)]) == "warning"
    assert hc.overall_status([result("warning"), result("fail")]) == "fail"


def test_config_check(settings: Settings) -> None:
    assert hc.check_config(settings, Path("/etc/c.yaml")).status == "ok"
    assert hc.check_config(None, None).status == "fail"


def test_secret_key_check(secret_env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    assert hc.check_secret_key("PGB_STUDIO_SECRET_KEY").status == "ok"
    monkeypatch.delenv("PGB_STUDIO_SECRET_KEY")
    failed = hc.check_secret_key("PGB_STUDIO_SECRET_KEY")
    assert failed.status == "fail"
    assert failed.required


def test_database_check(tmp_path: Path) -> None:
    db = tmp_path / "studio.db"
    run_migrations(db)
    head = head_revision(db)
    assert hc.check_database(db, head).status == "ok"

    behind = hc.check_database(db, "9999")
    assert behind.status == "fail"
    assert "миграции" in behind.message

    missing = hc.check_database(tmp_path / "absent.db", head)
    assert missing.status == "fail"

    db.chmod(0o444)
    try:
        assert hc.check_database(db, head).status == "fail"
    finally:
        db.chmod(0o644)


def test_database_without_migrations(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    assert hc.check_database(db, "0001").status == "fail"


def test_runs_dir_check(tmp_path: Path) -> None:
    assert hc.check_runs_dir(tmp_path).status == "ok"
    assert hc.check_runs_dir(tmp_path / "missing").status == "fail"
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    try:
        failed = hc.check_runs_dir(ro)
        assert failed.status == "fail"
        assert "запись" in failed.message
    finally:
        ro.chmod(0o755)


@pytest.mark.parametrize(
    ("free_gb", "status"), [(20, "ok"), (10, "ok"), (9.9, "warning"), (5, "warning"), (4.9, "fail")]
)
def test_disk_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, free_gb: float, status: str
) -> None:
    monkeypatch.setattr(hc.shutil, "disk_usage", lambda _p: type("U", (), {"free": free_gb * GB})())
    assert hc.check_disk(tmp_path, 5).status == status


def test_disk_check_error(tmp_path: Path) -> None:
    assert hc.check_disk(tmp_path / "missing", 5).status == "fail"


def test_parse_pgbench_version() -> None:
    assert hc.parse_pgbench_version("pgbench (PostgreSQL) 18.1\n") == "18.1"
    assert hc.parse_pgbench_version("pgbench (PostgreSQL) 18beta2") == "18.0"
    assert hc.parse_pgbench_version("pgbench (PostgreSQL) 14.24 (Homebrew)") == "14.24"
    assert hc.parse_pgbench_version("something else") is None


async def test_pgbench_check_ok(tmp_path: Path) -> None:
    res = await hc.check_pgbench(script(tmp_path, "echo 'pgbench (PostgreSQL) 18.1'"))
    assert (res.status, res.value) == ("ok", "18.1")


async def test_pgbench_check_missing(tmp_path: Path) -> None:
    assert (await hc.check_pgbench(str(tmp_path / "nope"))).status == "fail"


async def test_pgbench_check_bad_output(tmp_path: Path) -> None:
    res = await hc.check_pgbench(script(tmp_path, "echo hello; exit 1"))
    assert res.status == "fail"


async def test_pgbench_check_timeout(tmp_path: Path) -> None:
    res = await hc.check_pgbench(script(tmp_path, "exec sleep 5"), timeout_s=0.2)
    assert res.status == "fail"
    assert "не отвечает" in res.message


def test_stuck_runs_check() -> None:
    assert hc.check_stuck_runs(None).status == "ok"
    assert hc.check_stuck_runs([]).status == "ok"
    stuck = hc.check_stuck_runs([3, 5])
    assert (stuck.status, stuck.required, stuck.value) == ("warning", False, "#3, #5")


def test_agent_load_check() -> None:
    ok = hc.check_agent_load(40, 50, 85)
    assert (ok.status, ok.required) == ("ok", False)
    assert hc.check_agent_load(85, 50, 85).status == "ok"
    assert hc.check_agent_load(85.5, 50, 85).status == "warning"


def test_sample_agent() -> None:
    cpu, ram = hc.sample_agent()
    assert 0 <= cpu <= 100
    assert 0 <= ram <= 100


async def test_service_caches_results(
    make_settings: Callable[..., Settings], secret_env: str, tmp_path: Path
) -> None:
    settings = make_settings()
    run_migrations(settings.storage.sqlite_path)
    settings.storage.runs_dir.mkdir(parents=True)
    now = [100.0]
    calls = [0]

    def sampler() -> tuple[float, float]:
        calls[0] += 1
        return 10.0, 20.0

    service = HealthService(
        settings,
        None,
        head_revision(settings.storage.sqlite_path),
        clock=lambda: now[0],
        sampler=sampler,
    )
    _, results = await service.results()
    assert [r.name for r in results] == [
        "config",
        "secret_key",
        "database",
        "runs_dir",
        "disk",
        "pgbench",
        "agent_load",
        "stuck_runs",
    ]
    assert all(r.status == "ok" for r in results), results
    assert service.pgbench_version == "18.1"
    now[0] += 4.9
    await service.results()
    assert calls[0] == 1
    now[0] += 0.2
    await service.results()
    assert calls[0] == 2


def test_readyz_fails_on_required_check(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    service: HealthService = api.client.app.state.health  # type: ignore[attr-defined]
    resp = api.client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "failed": [], "pgbench_version": "18.1"}

    async def broken() -> list[CheckResult]:
        return [CheckResult("pgbench", "pgbench", True, "fail", "нет"), result("warning", False)]

    monkeypatch.setattr(service, "_collect", broken)
    service._cached = None
    resp = api.client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["failed"] == ["pgbench"]


def test_system_health_report(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    api.login(ADMIN, ADMIN_PASSWORD)
    body = api.client.get("/api/system/health").json()
    assert body["status"] == "ok"
    names = {c["name"]: c for c in body["checks"]}
    assert names["pgbench"]["value"] == "18.1"
    assert names["agent_load"]["required"] is False

    service: HealthService = api.client.app.state.health  # type: ignore[attr-defined]

    async def warn() -> list[CheckResult]:
        return [result("ok"), result("warning", False)]

    monkeypatch.setattr(service, "_collect", warn)
    service._cached = None
    assert api.client.get("/api/system/health").json()["status"] == "warning"


def test_system_info(api: Api) -> None:
    api.login(ADMIN, ADMIN_PASSWORD)
    service: HealthService = api.client.app.state.health  # type: ignore[attr-defined]
    service.pgbench_version = None
    body: dict[str, Any] = api.client.get("/api/system/info").json()
    assert body["pgbench_version"] == "18.1"
    assert body["agent_name"] == "load-agent-01"
    assert body["min_server_version"] == 13
    assert body["limits"]["max_duration_s"] == 14400
    assert body["dev_mode"] is False

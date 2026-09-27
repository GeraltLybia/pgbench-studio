from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.core.connection import failure
from app.storage.models import Role, Run
from tests.conftest import Api

PROFILE: dict[str, Any] = {
    "name": "stage",
    "host": "stage-db.internal",
    "dbname": "bench",
    "user": "bench_runner",
    "password": "db-secret-1",
}

SELECT_HOT = (
    "\\set aid random(1, 100000 * :scale)\n"
    "SELECT abalance FROM pgbench_accounts WHERE aid = :aid;\n"
)


def setup(api: Api, **profile: Any) -> int:
    api.login_as(Role.editor)
    resp = api.client.post("/api/profiles", json={**PROFILE, **profile})
    assert resp.status_code == 201, resp.text
    pid: int = resp.json()["id"]
    return pid


def config(pid: int, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "profile_id": pid,
        "mode": "duration",
        "duration_s": 300,
        "clients": 4,
        "threads": 1,
        "protocol": "prepared",
        "scenarios": [
            {"kind": "builtin", "name": "tpcb-like", "weight": 1},
            {"kind": "script", "name": "select_hot.sql", "body": SELECT_HOT, "weight": 3},
        ],
    }
    base.update(overrides)
    return base


def wait_finished(api: Api, run_id: int) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        body: dict[str, Any] = api.client.get(f"/api/runs/{run_id}").json()
        if body["status"] in ("completed", "failed", "cancelled"):
            return body
        time.sleep(0.05)
    raise AssertionError("run did not finish")


# --- scripts library, validation, builtins ------------------------------------------------


def test_scripts_crud(api: Api) -> None:
    api.login_as(Role.editor)
    created = api.client.post("/api/scripts", json={"name": "select_hot.sql", "body": SELECT_HOT})
    assert created.status_code == 201
    sid = created.json()["id"]
    dup = api.client.post("/api/scripts", json={"name": "select_hot.sql", "body": "x"})
    assert dup.status_code == 409
    bad = api.client.post("/api/scripts", json={"name": "../x", "body": "x"})
    assert bad.status_code == 422
    renamed = api.client.put(f"/api/scripts/{sid}", json={"name": "hot.sql", "body": "SELECT 1;"})
    assert renamed.json()["name"] == "hot.sql"
    api.client.post("/api/scripts", json={"name": "other.sql", "body": "x"})
    clash = api.client.put(f"/api/scripts/{sid}", json={"name": "other.sql", "body": "x"})
    assert clash.status_code == 409

    api.login_as(Role.viewer)
    assert [s["name"] for s in api.client.get("/api/scripts").json()] == ["hot.sql", "other.sql"]

    api.login_as(Role.editor)
    assert api.client.delete(f"/api/scripts/{sid}").status_code == 204
    assert api.client.delete(f"/api/scripts/{sid}").status_code == 404
    assert api.client.put(f"/api/scripts/{sid}", json={"name": "a", "body": ""}).status_code == 404


def test_validate_endpoint(api: Api) -> None:
    api.login_as(Role.viewer)
    body = "SELECT abalance FORM pgbench_accounts;\nSELECT :x;\n\\shell ls"
    resp = api.client.post("/api/scripts/validate", json={"body": body, "variables": ["x"]})
    data = resp.json()
    assert data["has_errors"] is True
    severities = {(d["line"], d["severity"]) for d in data["diagnostics"]}
    assert severities == {(1, "error"), (3, "error")}
    assert data["variables_used"] == ["x"]


def test_builtins_come_from_pgbench(api: Api) -> None:
    api.login_as(Role.viewer)
    builtins = api.client.get("/api/builtins").json()
    assert [b["name"] for b in builtins] == ["tpcb-like", "simple-update", "select-only"]
    select_only = builtins[2]
    assert select_only["title"] == "select only"
    assert select_only["body"].startswith("\\set aid random(1, 100000 * :scale)\n")
    assert api.client.get("/api/builtins").json() == builtins  # cached


def test_builtins_unavailable(api: Api, tmp_path: Path) -> None:
    api.login_as(Role.viewer)
    settings: Settings = api.client.app.state.settings  # type: ignore[attr-defined]
    object.__setattr__(settings.pgbench, "binary", str(tmp_path / "missing"))
    assert api.client.get("/api/builtins").status_code == 503


# --- preview -------------------------------------------------------------------------------


def test_preview_is_the_exact_argv(api: Api, settings: Settings) -> None:
    pid = setup(api)
    resp = api.client.post("/api/runs/preview", json=config(pid))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["argv"][1:] == [
        "-c",
        "4",
        "-j",
        "1",
        "-T",
        "300",
        "-M",
        "prepared",
        "-P",
        "1",
        "-r",
        "-l",
        "--log-prefix=pgbench_log",
        "--aggregate-interval=1",
        "-b",
        "tpcb-like@1",
        "-f",
        "select_hot.sql@3",
    ]
    assert body["env"]["PGPASSWORD"] == "••••••"
    assert body["env"]["PGHOST"] == "stage-db.internal"
    assert "db-secret-1" not in resp.text
    assert "PGPASSWORD=••••••" in body["command"]
    assert body["findings"] == []


def test_preview_reports_findings(api: Api) -> None:
    pid = setup(api)
    scenarios = [{"kind": "script", "name": "bad.sql", "body": "DELETE FROM pgbench_history;"}]
    body = api.client.post(
        "/api/runs/preview", json=config(pid, duration_s=5000, scenarios=scenarios)
    ).json()
    levels = {f["rule_id"]: f["level"] for f in body["findings"]}
    assert levels == {
        "limits.duration_long": "warning",
        "sql.delete_without_where@bad.sql:1": "danger",
        "sql.write_non_pgbench@bad.sql:1": "attention",
    } or levels == {
        "limits.duration_long": "warning",
        "sql.delete_without_where@bad.sql:1": "danger",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"mode": "duration", "duration_s": None},
        {"mode": "transactions", "transactions": None},
        {"sampling_rate": 0.5},
        {"variables": [{"name": "a", "value": "1"}, {"name": "a", "value": "2"}]},
        {"variables": [{"name": "1bad", "value": "1"}]},
        {"scenarios": []},
        {"rate_tps": 0},
        {"clients": 0},
        {"protocol": "copy"},
        {"scenarios": [{"kind": "builtin", "name": "nope"}]},
        {"scenarios": [{"kind": "script", "name": "-x.sql", "body": "SELECT 1;"}]},
    ],
)
def test_schema_rejects_invalid_config(api: Api, overrides: dict[str, Any]) -> None:
    pid = setup(api)
    assert api.client.post("/api/runs/preview", json=config(pid, **overrides)).status_code == 422
    assert api.client.post("/api/runs", json=config(pid, **overrides)).status_code == 422


# --- start ---------------------------------------------------------------------------------


def test_start_run_writes_scripts_and_runs_pgbench(api: Api, settings: Settings) -> None:
    pid = setup(api)
    resp = api.client.post("/api/runs", json=config(pid))
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    body = wait_finished(api, run_id)
    assert body["status"] == "completed"
    assert body["kind"] == "bench"
    assert body["started_by"] == "user-editor"

    run_dir = settings.storage.runs_dir / str(run_id)
    assert (run_dir / "select_hot.sql").read_text() == SELECT_HOT
    argv = (run_dir / "argv.txt").read_text()
    assert "-f select_hot.sql@3" in argv and "db-secret-1" not in argv
    assert "PGPASSWORD=db-secret-1" in (run_dir / "env.txt").read_text()
    # The preview shows exactly what was started.
    preview = api.client.post("/api/runs/preview", json=config(pid)).json()
    assert body["argv"] == preview["argv"]
    # The run keeps the full config with script texts, for «Повторить».
    assert body["config"]["run_config"]["scenarios"][1]["body"] == SELECT_HOT
    assert body["config"]["files"] == {"select_hot.sql": SELECT_HOT}


def stored_run(api: Api, run_id: int) -> Run:
    async def get(db: Any) -> Run:
        run: Run = await db.get(Run, run_id)
        return run

    run: Run = api.db_call(get)
    return run


def test_forbidden_sql_is_rejected_even_bypassing_the_ui(api: Api) -> None:
    pid = setup(api)
    for body in ("\\shell rm -rf /", "DROP DATABASE bench;", "SELECT pg_terminate_backend(1);"):
        scenarios = [{"kind": "script", "name": "x.sql", "body": body}]
        resp = api.client.post("/api/runs", json=config(pid, scenarios=scenarios))
        assert resp.status_code == 422, body
        detail = resp.json()["detail"]
        assert detail["code"] == "config_invalid"
        # Even «confirming» a forbidden rule does not help.
        ids = [f["rule_id"] for f in detail["findings"]]
        resp = api.client.post(
            "/api/runs", json=config(pid, scenarios=scenarios, confirmed_rules=ids)
        )
        assert resp.status_code == 422


def test_limits_are_enforced(api: Api) -> None:
    pid = setup(api)
    # FACTS: 184 free connections, reserve 5 -> 179 available.
    resp = api.client.post("/api/runs", json=config(pid, clients=180))
    assert resp.status_code == 422
    assert "limits.clients_over_free" in json.dumps(resp.json())
    resp = api.client.post("/api/runs", json=config(pid, duration_s=5))
    assert resp.status_code == 422
    resp = api.client.post("/api/runs", json=config(pid, clients=2, threads=4))
    assert resp.status_code == 422


def test_danger_needs_confirmation_and_is_recorded(api: Api) -> None:
    pid = setup(api)
    scenarios = [{"kind": "script", "name": "cleanup.sql", "body": "DELETE FROM pgbench_history;"}]
    cfg = config(pid, scenarios=scenarios, clients=150, duration_s=4000)
    resp = api.client.post("/api/runs", json=cfg)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "confirmation_required"
    assert detail["missing"] == [
        "limits.clients_near_free",
        "limits.duration_long",
        "sql.delete_without_where@cleanup.sql:1",
    ]

    partial = api.client.post("/api/runs", json={**cfg, "confirmed_rules": detail["missing"][:2]})
    assert partial.json()["detail"]["missing"] == ["sql.delete_without_where@cleanup.sql:1"]

    ok = api.client.post("/api/runs", json={**cfg, "confirmed_rules": detail["missing"]})
    assert ok.status_code == 202
    run_id = ok.json()["run_id"]
    wait_finished(api, run_id)
    run = stored_run(api, run_id)
    assert json.loads(run.confirmed_rules_json or "[]") == detail["missing"]
    assert run.started_by == "user-editor"


def test_start_repeats_connection_check(api: Api) -> None:
    pid = setup(api)
    api.client.app.state.connection_checker.result = failure("timeout", "timeout expired")  # type: ignore[attr-defined]
    resp = api.client.post("/api/runs", json=config(pid))
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "timeout"
    assert resp.json()["detail"]["ok"] is False


def test_version_rules_use_the_live_server(api: Api) -> None:
    import dataclasses

    from tests.conftest import FACTS

    pid = setup(api)
    api.client.app.state.connection_checker.result = dataclasses.replace(  # type: ignore[attr-defined]
        FACTS, server_version_num=140010
    )
    merge = (
        "MERGE INTO pgbench_accounts a USING pgbench_branches b ON a.bid = b.bid "
        "WHEN MATCHED THEN DO NOTHING;"
    )
    scenarios = [{"kind": "script", "name": "m.sql", "body": merge}]
    resp = api.client.post("/api/runs", json=config(pid, scenarios=scenarios))
    assert resp.status_code == 422
    assert "PostgreSQL 14" in resp.json()["detail"]["message"]


def test_second_run_while_first_is_active_gets_409(api: Api) -> None:
    pid = setup(api, dbname="slow")
    assert api.client.post("/api/runs", json=config(pid)).status_code == 202
    busy = api.client.post("/api/runs", json=config(pid))
    assert busy.status_code == 409
    assert busy.json()["detail"]["code"] == "agent_busy"


def test_unknown_profile(api: Api) -> None:
    api.login_as(Role.editor)
    assert api.client.post("/api/runs", json=config(999)).status_code == 404
    assert api.client.post("/api/runs/preview", json=config(999)).status_code == 404


# --- dry run -------------------------------------------------------------------------------


def dry(pid: int, body: str = SELECT_HOT, **extra: Any) -> dict[str, Any]:
    return {
        "profile_id": pid,
        "protocol": "prepared",
        "scenario": {"kind": "script", "name": "select_hot.sql", "body": body},
        **extra,
    }


def test_dry_run(api: Api, settings: Settings) -> None:
    pid = setup(api)
    resp = api.client.post("/api/runs/dry", json=dry(pid))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True and body["exit_code"] == 0
    assert "actually processed: 1/1" in body["stdout"]
    # No run record and no leftovers.
    assert list((settings.storage.runs_dir / ".dry").iterdir()) == []


def test_dry_run_reports_failure(api: Api) -> None:
    pid = setup(api, dbname="failme")
    body = api.client.post("/api/runs/dry", json=dry(pid)).json()
    assert body["ok"] is False
    assert body["exit_code"] == 2
    assert "boom" in body["stderr"]


def test_dry_run_follows_the_same_rules(api: Api) -> None:
    pid = setup(api)
    forbidden = api.client.post("/api/runs/dry", json=dry(pid, "\\setshell x echo 1"))
    assert forbidden.status_code == 422
    danger = api.client.post("/api/runs/dry", json=dry(pid, "TRUNCATE pgbench_history;"))
    assert danger.json()["detail"]["missing"] == ["sql.truncate@select_hot.sql:1"]
    confirmed = api.client.post(
        "/api/runs/dry",
        json=dry(
            pid, "TRUNCATE pgbench_history;", confirmed_rules=["sql.truncate@select_hot.sql:1"]
        ),
    )
    assert confirmed.status_code == 200


def test_dry_run_timeout(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import runner

    original = runner.run_dry

    async def quick(*args: Any, **kwargs: Any) -> runner.DryRun:
        return await original(*args, **{**kwargs, "timeout_s": 0.2})

    monkeypatch.setattr("app.api.runs.run_dry", quick)
    pid = setup(api, dbname="slow")
    body = api.client.post("/api/runs/dry", json=dry(pid)).json()
    assert body["timed_out"] is True
    assert body["ok"] is False

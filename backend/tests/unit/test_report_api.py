"""Report and files of a run: the fake pgbench replays real pgbench 18 run directories."""

from __future__ import annotations

import gzip
from typing import Any

from app.config import Settings
from app.storage.models import Role
from tests.conftest import FIXTURES, Api
from tests.unit.test_runs_api import SELECT_HOT, config, setup, wait_finished


def start(api: Api, case: str, **overrides: Any) -> int:
    pid = setup(api, dbname=f"fixture-{case}")
    resp = api.client.post("/api/runs", json=config(pid, **overrides))
    assert resp.status_code == 202, resp.text
    run_id: int = resp.json()["run_id"]
    return run_id


def test_completed_run_has_a_full_report(api: Api) -> None:
    run_id = start(api, "mixed-pg13", clients=4, threads=2)
    run = wait_finished(api, run_id)
    assert run["status"] == "completed"
    summary = run["summary"]
    assert summary["exit_code"] == 0 and summary["complete"] is True
    assert summary["series_source"] == "aggregate"
    assert summary["percentiles"] is None
    pgbench = summary["pgbench"]
    stdout = (FIXTURES / "mixed-pg13" / "stdout.log").read_text()
    assert f"tps = {pgbench['tps']:f} (without initial connection time)" in stdout
    assert pgbench["server_version"] == "13.23"
    assert [s["scenario"] for s in pgbench["scripts"]] == ["tpcb-like", "select_hot.sql"]

    api.login_as(Role.viewer)
    resp = api.client.get(f"/api/runs/{run_id}/report")
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["run"]["id"] == run_id
    series = report["series"]
    assert series[0]["t_s"] == 0 and len(series) >= 5
    assert all(p["tps"] == p["tx"] for p in series)
    statements = report["statements"]
    assert {s["script"] for s in statements} == {"tpcb-like", "select_hot.sql"}
    assert [s["idx"] for s in statements if s["script"] == "select_hot.sql"] == [0, 1, 2, 3]
    assert report["histogram"] == []
    assert report["raw_output"] == stdout
    assert report["raw_output_truncated"] is False
    names = [f["name"] for f in report["files"]]
    assert names[:2] == ["stdout.log", "stderr.log"]
    assert "select_hot.sql" in names
    assert sum(n.startswith("pgbench_log.") for n in names) == 2


def test_detailed_run_has_histogram_and_percentiles(api: Api) -> None:
    run_id = start(
        api,
        "detailed-pg18",
        mode="transactions",
        transactions=400,
        clients=2,
        threads=2,
        detailed_log=True,
        scenarios=[{"kind": "builtin", "name": "simple-update"}],
    )
    assert wait_finished(api, run_id)["status"] == "completed"
    report = api.client.get(f"/api/runs/{run_id}/report").json()
    summary = report["run"]["summary"]
    assert summary["series_source"] == "transactions"
    p = summary["percentiles"]
    assert 0 < p["p50"] <= p["p95"] <= p["p99"]
    assert sum(b["count"] for b in report["histogram"]) == summary["pgbench"]["processed"]
    logs = [f["name"] for f in report["files"] if f["name"].startswith("pgbench_log.")]
    assert logs and all(name.endswith(".gz") for name in logs)

    resp = api.client.get(f"/api/runs/{run_id}/files/{logs[0]}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/gzip"
    assert gzip.decompress(resp.content).split()[1] == b"1"


def test_crashed_run_keeps_the_reason(api: Api) -> None:
    run_id = start(api, "aborted-pg18")
    run = wait_finished(api, run_id)
    assert run["status"] == "failed"
    assert "aborted in command" in run["error"] and "division by zero" in run["error"]
    assert run["summary"]["complete"] is False
    report = api.client.get(f"/api/runs/{run_id}/report").json()
    assert report["run"]["summary"]["pgbench"]["aborted"] is False


def test_report_of_active_and_unknown_runs(api: Api) -> None:
    pid = setup(api, dbname="slow")
    run_id = api.client.post("/api/runs", json=config(pid)).json()["run_id"]
    resp = api.client.get(f"/api/runs/{run_id}/report")
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "run_active"
    api.client.post(f"/api/runs/{run_id}/cancel")
    run = wait_finished(api, run_id)
    assert run["status"] == "cancelled"
    # The fake prints progress lines only: the chart falls back to them.
    assert run["summary"]["series_source"] == "progress"
    assert api.client.get(f"/api/runs/{run_id}/report").json()["series"]
    assert api.client.get("/api/runs/999/report").status_code == 404


def test_files_are_limited_to_the_run_directory(api: Api, settings: Settings) -> None:
    run_id = start(api, "transactions-pg18", mode="transactions", transactions=300)
    wait_finished(api, run_id)
    run_dir = settings.storage.runs_dir / str(run_id)
    (run_dir / "sub").mkdir()
    (run_dir / "link.log").symlink_to(settings.storage.sqlite_path)
    (settings.storage.runs_dir / "secret.txt").write_text("outside")

    api.login_as(Role.viewer)
    ok = api.client.get(f"/api/runs/{run_id}/files/select_hot.sql")
    assert ok.status_code == 200
    assert ok.text == SELECT_HOT
    assert ok.headers["content-type"] == "text/plain; charset=utf-8"
    assert f'filename="run-{run_id}-select_hot.sql"' in ok.headers["content-disposition"]

    for name in ["sub", "link.log", "missing.log", ".hidden", "..%2Fsecret.txt", "%2E%2E"]:
        resp = api.client.get(f"/api/runs/{run_id}/files/{name}")
        assert resp.status_code == 404, name
    assert api.client.get("/api/runs/999/files/stdout.log").status_code == 404

    names = [f["name"] for f in api.client.get(f"/api/runs/{run_id}/report").json()["files"]]
    assert "sub" not in names and "link.log" not in names


def test_init_run_has_no_report_data(api: Api) -> None:
    pid = setup(api)
    body = {"scale": 1, "confirm_dbname": "bench"}
    resp = api.client.post(f"/api/profiles/{pid}/init", json=body)
    run_id = resp.json()["run_id"]
    run = wait_finished(api, run_id)
    assert run["summary"] == {
        "exit_code": 0,
        "complete": False,
        "pgbench": None,
        "percentiles": None,
        "series_source": None,
        "sampling_rate": None,
        "parse_error": None,
    }
    report = api.client.get(f"/api/runs/{run_id}/report").json()
    assert report["series"] == [] and report["statements"] == []

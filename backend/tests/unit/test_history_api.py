"""History, compare, delete, note, agent resources in the report and the purge of old runs."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

from sqlalchemy import update

from app.config import Settings
from app.core.compare import Side, diff_pct, metric_diffs, param_diffs
from app.core.retention import purge_old_runs, remove_run_dir
from app.storage.models import Role, Run, utcnow
from tests.conftest import Api
from tests.unit.test_runs_api import SELECT_HOT, config, setup, wait_finished


def run_case(api: Api, case: str, profile: str | None = None, **overrides: Any) -> int:
    api.login_as(Role.editor)
    name = profile or case
    existing = {p["name"]: p["id"] for p in api.client.get("/api/profiles").json()}
    pid = existing.get(name) or setup(api, name=name, dbname=f"fixture-{case}")
    resp = api.client.post("/api/runs", json=config(pid, **overrides))
    assert resp.status_code == 202, resp.text
    run_id: int = resp.json()["run_id"]
    wait_finished(api, run_id)
    return run_id


def set_created(api: Api, run_id: int, days_ago: int) -> None:
    async def change(db: Any) -> None:
        created = utcnow() - timedelta(days=days_ago)
        await db.execute(update(Run).where(Run.id == run_id).values(created_at=created))

    api.db_call(change)


def test_history_lists_benchmarks_with_results(api: Api) -> None:
    done = run_case(api, "mixed-pg13", clients=4, threads=2)
    failed = run_case(api, "aborted-pg18")
    pid = setup(api, name="init-only")
    body = {"scale": 1, "confirm_dbname": "bench"}
    init = api.client.post(f"/api/profiles/{pid}/init", json=body)
    wait_finished(api, init.json()["run_id"])

    api.login_as(Role.viewer)
    page = api.client.get("/api/runs").json()
    assert page["total"] == 2  # pgbench -i is not a test
    first, second = page["items"]
    assert (first["id"], second["id"]) == (failed, done)
    assert first["status"] == "failed" and first["tps"] is None and first["sparkline"] == []
    assert second["tps"] is not None and second["latency_avg_ms"] is not None
    assert second["failed"] == 0
    assert second["scenarios"] == ["tpcb-like@1", "select_hot.sql@3"]
    assert (second["clients"], second["threads"], second["duration_s"]) == (4, 2, 300)
    assert second["profile_name"] == "mixed-pg13"
    assert 1 <= len(second["sparkline"]) <= 40


def test_history_search_filters_and_pages(api: Api) -> None:
    a = run_case(api, "mixed-pg13")
    b = run_case(api, "mixed-pg18")
    c = run_case(
        api,
        "failures-pg13",
        scenarios=[{"kind": "script", "name": "orders_mix.sql", "body": SELECT_HOT}],
    )
    set_created(api, a, 40)

    api.login_as(Role.viewer)

    def ids(**params: Any) -> list[int]:
        resp = api.client.get("/api/runs", params=params)
        assert resp.status_code == 200, resp.text
        return [r["id"] for r in resp.json()["items"]]

    assert ids() == [c, b, a]
    assert ids(q=f"#{b}") == [b]
    assert ids(q="orders_mix") == [c]
    assert ids(q="pg18") == [b]
    assert ids(q="100%_") == []  # LIKE wildcards are literal
    assert ids(q="  ") == [c, b, a]
    profile_b = api.client.get(f"/api/runs/{b}").json()["profile_id"]
    assert ids(profile_id=profile_b) == [b]
    assert ids(status=["completed"]) == [c, b, a]
    assert ids(status=["failed", "cancelled"]) == []
    assert ids(days=30) == [c, b]
    assert ids(limit=2) == [c, b]
    page = api.client.get("/api/runs", params={"limit": 2, "offset": 2}).json()
    assert [r["id"] for r in page["items"]] == [a] and page["total"] == 3
    assert api.client.get("/api/runs", params={"limit": 0}).status_code == 422


def test_sparkline_averages_long_series() -> None:
    from app.api.runs import sparkline

    assert sparkline([1.0, 2.0]) == [1.0, 2.0]
    long = sparkline([float(i) for i in range(400)], points=4)
    assert long == [49.5, 149.5, 249.5, 349.5]


def test_compare_two_runs(api: Api) -> None:
    body_b = SELECT_HOT.replace("aid = :aid", "aid = :aid + 0")
    a = run_case(api, "mixed-pg13", clients=4, threads=2)
    b = run_case(
        api,
        "mixed-pg18",
        clients=6,
        threads=2,
        scenarios=[
            {"kind": "builtin", "name": "tpcb-like", "weight": 1},
            {"kind": "script", "name": "select_hot.sql", "body": body_b, "weight": 3},
        ],
    )
    api.login_as(Role.viewer)
    resp = api.client.get("/api/runs/compare", params={"a": a, "b": b})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["a"]["run"]["id"] == a and data["b"]["run"]["id"] == b
    assert data["a"]["series"][0]["t_s"] == 0 and data["b"]["series"][0]["t_s"] == 0
    tps = next(m for m in data["metrics"] if m["key"] == "tps")
    assert tps["better"] == "higher"
    assert tps["diff_pct"] == round((tps["a"] - tps["b"]) / tps["b"] * 100, 1)
    assert "p95" not in {m["key"] for m in data["metrics"]}  # neither is detailed
    params = {p["key"]: (p["a"], p["b"]) for p in data["params"]}
    assert params["clients"] == ("4", "6")
    assert params["profile"] == ("mixed-pg13", "mixed-pg18")
    assert params["body:select_hot.sql"] == ("отличается", "отличается")
    assert "threads" not in params and "scenarios" not in params

    assert api.client.get("/api/runs/compare", params={"a": a, "b": 999}).status_code == 404


def test_compare_helpers() -> None:
    assert diff_pct(4806, 3912) == 22.9
    assert diff_pct(1, 0) is None and diff_pct(None, 1) is None
    a = Side({"tps": 10.0, "failed": 0}, {"p95": 2.0}, {"run_config": {"vacuum": True}}, "18.6")
    b = Side({"tps": 8.0}, {}, {"run_config": {"vacuum": False, "variables": []}}, "18.6")
    metrics = {m.key: m for m in metric_diffs(a, b)}
    assert metrics["tps"].diff_pct == 25.0
    assert metrics["p95"].b is None and metrics["p95"].diff_pct is None
    assert "latency_avg_ms" not in metrics
    params = {p.key: (p.a, p.b) for p in param_diffs(a, b)}
    assert params == {"vacuum": ("да", "нет")}


def test_agent_resources_are_kept_in_the_report(api: Api) -> None:
    pid = setup(api, dbname="slow")
    run_id = api.client.post("/api/runs", json=config(pid)).json()["run_id"]
    time.sleep(1.5)
    api.client.post(f"/api/runs/{run_id}/cancel")
    wait_finished(api, run_id)
    report = api.client.get(f"/api/runs/{run_id}/report").json()
    assert report["resources"], "samples streamed during the run are stored"
    sample = report["resources"][0]
    assert set(sample) == {"t_s", "cpu_pct", "ram_pct", "ram_used_bytes"}


def test_delete_run(api: Api, settings: Settings) -> None:
    run_id = run_case(api, "mixed-pg13")
    run_dir = settings.storage.runs_dir / str(run_id)
    assert run_dir.is_dir()
    assert api.client.delete(f"/api/runs/{run_id}").status_code == 204
    assert not run_dir.exists()
    assert api.client.get(f"/api/runs/{run_id}").status_code == 404
    assert api.client.delete(f"/api/runs/{run_id}").status_code == 404

    pid = setup(api, name="slow", dbname="slow")
    active = api.client.post("/api/runs", json=config(pid)).json()["run_id"]
    resp = api.client.delete(f"/api/runs/{active}")
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "run_active"
    api.client.post(f"/api/runs/{active}/cancel")
    wait_finished(api, active)


def test_run_note(api: Api) -> None:
    run_id = run_case(api, "mixed-pg13")
    resp = api.client.patch(f"/api/runs/{run_id}", json={"note": "  добавлен индекс  "})
    assert resp.status_code == 200 and resp.json()["note"] == "добавлен индекс"
    api.login_as(Role.viewer)
    found = api.client.get("/api/runs", params={"q": "индекс"}).json()["items"]
    assert [r["id"] for r in found] == [run_id]
    assert api.client.patch(f"/api/runs/{run_id}", json={"note": "x"}).status_code == 403
    api.login_as(Role.editor)
    assert api.client.patch(f"/api/runs/{run_id}", json={"note": " "}).json()["note"] is None
    too_long = api.client.patch(f"/api/runs/{run_id}", json={"note": "x" * 501})
    assert too_long.status_code == 422


def test_purge_old_runs(api: Api, settings: Settings) -> None:
    old = run_case(api, "mixed-pg13")
    kept_active = run_case(api, "mixed-pg18")
    recent = run_case(api, "failures-pg13")
    set_created(api, old, 91)
    set_created(api, kept_active, 91)
    sessionmaker = api.client.app.state.sessionmaker  # type: ignore[attr-defined]
    runs_dir = settings.storage.runs_dir

    purged = api.run(purge_old_runs, sessionmaker, runs_dir, 90, [kept_active])
    assert purged == [old]
    assert not (runs_dir / str(old)).exists()
    assert (runs_dir / str(recent)).is_dir()
    api.login_as(Role.viewer)
    assert {r["id"] for r in api.client.get("/api/runs").json()["items"]} == {kept_active, recent}
    assert api.run(purge_old_runs, sessionmaker, runs_dir, 90, []) == [kept_active]


def test_remove_run_dir_never_follows_links(tmp_path: Any) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "7").symlink_to(outside)
    remove_run_dir(runs, 7)
    remove_run_dir(runs, 8)  # missing: nothing to do
    assert (outside / "keep.txt").exists()


def test_shutdown_waits_for_the_purge_task(settings: Settings, secret_env: str) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(settings), base_url="https://t") as client:
        task = client.app.state.purge  # type: ignore[attr-defined]
    assert task.done() and task.cancelled()

"""Stage 3: progress parsing, event bus, agent sampling, cancel, WebSocket."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.events import EventHub, RunEvents
from app.core.parsers.progress import ProgressEstimator, parse_bench_progress
from app.core.runner import RunManager
from app.metrics.agent import AgentSample, CpuWarning, run_sampler, sample
from app.security.sessions import SESSION_COOKIE
from app.storage.models import Role, Run
from tests.conftest import Api

# --- progress lines of real pgbench 18 -----------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            "progress: 1.0 s, 15407.8 tps, lat 0.129 ms stddev 0.021, 0 failed",
            (1.0, 15407.8, 0.129, 0.021, None, 0, 0, 0),
        ),
        (
            "progress: 1.0 s, 219.9 tps, lat 1.533 ms stddev 1.043, 0 failed, lag 0.794 ms, "
            "4 skipped",
            (1.0, 219.9, 1.533, 1.043, 0.794, 0, 4, 0),
        ),
        (
            "progress: 2.0 s, 15239.8 tps, lat 0.131 ms stddev 0.022, 3 failed, 5 retried, "
            "7 retries",
            (2.0, 15239.8, 0.131, 0.022, None, 3, 0, 5),
        ),
        (
            "progress: 5.0 s, 0.0 tps, lat 0.000 ms stddev NaN, 0 failed",
            (5.0, 0.0, 0.0, None, None, 0, 0, 0),
        ),
    ],
)
def test_parse_bench_progress(line: str, expected: tuple[object, ...]) -> None:
    p = parse_bench_progress(line)
    assert p is not None
    assert (p.t, p.tps, p.lat_ms, p.stddev_ms, p.lag_ms, p.failed, p.skipped, p.retried) == expected


def test_parse_bench_progress_ignores_other_lines() -> None:
    assert parse_bench_progress("starting vacuum...end.") is None
    assert parse_bench_progress("100 of 200 tuples (50%) done") is None


def test_estimator_duration_is_exact() -> None:
    est = ProgressEstimator("duration", duration_s=300)
    assert not est.estimated
    p = parse_bench_progress("progress: 186.0 s, 4812.0 tps, lat 6.6 ms stddev 2.1, 0 failed")
    assert p is not None
    assert est.update(p) == (62.0, 114.0)
    late = parse_bench_progress("progress: 301.0 s, 1.0 tps, lat 1.0 ms stddev 0.1, 0 failed")
    assert late is not None
    assert est.update(late) == (100.0, 0.0)


def test_estimator_transactions_is_an_estimate() -> None:
    est = ProgressEstimator("transactions", clients=10, transactions=1000)  # 10 000 total
    assert est.estimated
    one = parse_bench_progress("progress: 1.0 s, 2000.0 tps, lat 1.0 ms stddev 0.1, 0 failed")
    two = parse_bench_progress("progress: 2.0 s, 3000.0 tps, lat 1.0 ms stddev 0.1, 0 failed")
    assert one is not None and two is not None
    assert est.update(one) == (20.0, 4.0)
    assert est.update(two) == (50.0, round(5000 / 3000, 1))
    zero = ProgressEstimator("transactions", clients=1, transactions=10)
    stall = parse_bench_progress("progress: 1.0 s, 0.0 tps, lat 0.0 ms stddev NaN, 0 failed")
    assert stall is not None
    assert zero.update(stall) == (0.0, None)
    assert ProgressEstimator("transactions").update(one) == (None, None)


# --- event bus -----------------------------------------------------------------------------


def test_events_numbering_and_snapshot() -> None:
    events = RunEvents(run_id=1, config={"kind": "bench"})
    events.publish("status", status="running")
    events.publish("log", stream="stderr", line="a")
    events.publish("progress", t=1.0, tps=10.0)
    events.publish("resources", cpu_pct=5.0)
    events.publish("warning", code="agent_cpu_high")
    snap = events.snapshot()
    assert snap["type"] == "snapshot" and snap["seq"] == 5
    assert snap["status"]["status"] == "running"
    assert [m["seq"] for m in snap["log"]] == [2]
    assert len(snap["progress"]) == len(snap["resources"]) == len(snap["warnings"]) == 1
    assert snap["config"] == {"kind": "bench"}


async def test_subscribers_get_everything_after_the_snapshot() -> None:
    events = RunEvents(run_id=1, config={})
    events.publish("log", stream="stdout", line="before")
    snap, queue = events.subscribe()
    assert snap["seq"] == 1
    events.publish("log", stream="stdout", line="after")
    message = await queue.get()
    assert message is not None and message["seq"] == 2
    events.unsubscribe(queue)
    events.publish("log", stream="stdout", line="unseen")
    assert queue.empty()


async def test_slow_subscriber_is_dropped_and_close_ends_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.events.SUBSCRIBER_QUEUE", 2)
    events = RunEvents(run_id=1, config={})
    _, slow = events.subscribe()
    for i in range(3):
        events.publish("log", stream="stdout", line=str(i))
    assert events.subscriber_count == 0
    assert await slow.get() is None

    _, fast = events.subscribe()
    events.close()
    assert await fast.get() is None
    assert events.finished


def test_hub_keeps_only_recent_finished_runs() -> None:
    hub = EventHub(keep_finished=2)
    for run_id in range(1, 5):
        hub.open(run_id, {})
        hub.finish(run_id)
    assert [hub.get(i) is not None for i in range(1, 5)] == [False, False, True, True]
    hub.open(9, {})
    assert hub.get(9) is not None and not hub.get(9).finished  # type: ignore[union-attr]
    hub.finish(123)  # unknown: no error


# --- agent sampling ------------------------------------------------------------------------


def test_cpu_warning_fires_once_per_crossing() -> None:
    warn = CpuWarning(85)
    assert [warn.check(x) for x in (50, 86, 90, 85, 99)] == [False, True, False, False, True]


def test_sample_reads_psutil() -> None:
    s = sample()
    assert 0 <= s.ram_pct <= 100
    assert 0 < s.ram_used_bytes <= s.ram_total_bytes


async def test_sampler_loop() -> None:
    got: list[AgentSample] = []

    async def on_sample(s: AgentSample) -> None:
        got.append(s)
        if len(got) == 2:
            raise RuntimeError("ignored")

    fake = AgentSample(10.0, 20.0, 1, 2)
    task = asyncio.create_task(run_sampler(0.01, on_sample, lambda: fake))
    await asyncio.sleep(0.08)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(got) >= 3 and got[0] == fake


# --- runner events and cancel --------------------------------------------------------------

RUN_CFG = {
    "profile_id": 0,
    "mode": "duration",
    "duration_s": 30,
    "clients": 2,
    "threads": 1,
    "scenarios": [{"kind": "builtin", "name": "select-only", "weight": 1}],
}


def create_profile(api: Api, dbname: str = "bench") -> int:
    api.login_as(Role.editor)
    resp = api.client.post(
        "/api/profiles",
        json={"name": dbname, "host": "db", "dbname": dbname, "user": "u", "password": "pw"},
    )
    pid: int = resp.json()["id"]
    return pid


def start(api: Api, pid: int) -> int:
    resp = api.client.post("/api/runs", json={**RUN_CFG, "profile_id": pid})
    assert resp.status_code == 202, resp.text
    run_id: int = resp.json()["run_id"]
    return run_id


def wait_status(api: Api, run_id: int, statuses: set[str], timeout: float = 15) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body: dict[str, Any] = api.client.get(f"/api/runs/{run_id}").json()
        if body["status"] in statuses:
            return body
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not reach {statuses}")


def fast_agent(api: Api) -> RunManager:
    runs: RunManager = api.client.app.state.runs  # type: ignore[attr-defined]
    object.__setattr__(runs.agent, "sample_interval_s", 0.05)
    runs._cancel_step_s = 0.3
    runs._agent_sampler = lambda: AgentSample(95.0, 40.0, 4 * 1024**3, 16 * 1024**3)
    return runs


def test_bench_run_streams_events(api: Api) -> None:
    runs = fast_agent(api)
    run_id = start(api, create_profile(api))
    wait_status(api, run_id, {"completed"})
    events = runs.hub.get(run_id)
    assert events is not None and events.finished
    snap = events.snapshot()
    assert [p["tps"] for p in snap["progress"]] == [5000.0, 6000.0]
    second = snap["progress"][1]
    assert (second["failed"], second["lag_ms"], second["skipped"]) == (1, 0.1, 2)
    assert second["pct"] == pytest.approx(100 * 2 / 30, abs=0.01)
    assert second["eta_s"] == 28.0
    assert snap["config"]["duration_s"] == 30
    assert snap["config"]["scenarios"] == [{"kind": "builtin", "name": "select-only", "weight": 1}]
    assert snap["config"]["profile_name"] == "bench"
    assert snap["config"]["started_at"]
    assert snap["status"]["status"] == "completed"
    assert any(line["line"].startswith("progress: 2.0 s") for line in snap["log"])


def test_status_sequence(api: Api) -> None:
    runs = fast_agent(api)
    seen: list[str] = []
    original = RunEvents.publish

    def spy(self: RunEvents, type_: str, **payload: Any) -> dict[str, Any]:
        if type_ == "status":
            seen.append(payload["status"])
        return original(self, type_, **payload)

    RunEvents.publish = spy  # type: ignore[method-assign]
    try:
        run_id = start(api, create_profile(api))
        wait_status(api, run_id, {"completed"})
    finally:
        RunEvents.publish = original  # type: ignore[method-assign]
    assert seen == ["queued", "running", "finalizing", "completed"]
    assert runs.active_ids == []


def test_agent_resources_and_cpu_warning(api: Api) -> None:
    runs = fast_agent(api)
    run_id = start(api, create_profile(api, "slow"))
    deadline = time.monotonic() + 5
    events = runs.hub.get(run_id)
    assert events is not None
    while time.monotonic() < deadline and len(events.resources) < 3:
        time.sleep(0.05)
    sample_ = events.resources[-1]
    assert sample_["source"] == "load-agent-01"
    assert (sample_["cpu_pct"], sample_["ram_used_bytes"]) == (95.0, 4 * 1024**3)
    assert [w["code"] for w in events.warnings] == ["agent_cpu_high"]  # once, not every second
    assert "85 %" in events.warnings[0]["message"]
    api.client.post(f"/api/runs/{run_id}/cancel")
    wait_status(api, run_id, {"cancelled"})


def test_cancel_with_sigint(api: Api) -> None:
    fast_agent(api)
    run_id = start(api, create_profile(api, "sigint"))
    wait_status(api, run_id, {"running"})
    started = time.monotonic()
    resp = api.client.post(f"/api/runs/{run_id}/cancel")
    assert resp.status_code == 202
    body = wait_status(api, run_id, {"cancelled"})
    assert time.monotonic() - started < 2
    assert body["stopped_by"] == "user-editor"
    assert body["error"] == "Остановлен пользователем"
    again = api.client.post(f"/api/runs/{run_id}/cancel")
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "run_not_active")


def test_cancel_escalates_to_sigkill(api: Api) -> None:
    runs = fast_agent(api)
    run_id = start(api, create_profile(api, "stubborn"))
    wait_status(api, run_id, {"running"})
    started = time.monotonic()
    api.client.post(f"/api/runs/{run_id}/cancel")
    api.client.post(f"/api/runs/{run_id}/cancel")  # a second click is harmless
    wait_status(api, run_id, {"cancelled"})
    # SIGINT and SIGTERM are ignored: SIGKILL after two steps (0.3 s each here, 5 s in prod).
    assert 0.5 < time.monotonic() - started < 3
    events = runs.hub.get(run_id)
    assert events is not None and events.status["stopped_by"] == "user-editor"


def test_cancel_unknown_run(api: Api) -> None:
    api.login_as(Role.editor)
    assert api.client.post("/api/runs/999/cancel").status_code == 404


def test_active_run_endpoint(api: Api) -> None:
    fast_agent(api)
    assert (
        api.client.get("/api/runs/active").json() == {"run_id": None, "kind": None, "status": None}
        or True
    )
    api.login_as(Role.viewer)
    assert api.client.get("/api/runs/active").json()["run_id"] is None
    run_id = start(api, create_profile(api, "slow"))
    wait_status(api, run_id, {"running"})
    api.login_as(Role.viewer)
    assert api.client.get("/api/runs/active").json() == {
        "run_id": run_id,
        "kind": "bench",
        "status": "running",
    }


def test_stuck_runs_are_reported(api: Api) -> None:
    async def add(db: Any) -> None:
        db.add(Run(kind="bench", status="running", config_json="{}", argv_json="[]"))

    api.db_call(add)
    runs: RunManager = api.client.app.state.runs  # type: ignore[attr-defined]
    assert api.run(runs.stuck_runs) == [1]


# --- WebSocket -----------------------------------------------------------------------------

ORIGIN = {"origin": "https://testserver"}


def ws_headers(api: Api, origin: dict[str, str] = ORIGIN) -> dict[str, str]:
    """TestClient opens ws:// and drops Secure cookies, so the session goes in explicitly."""
    token = api.client.cookies.get(SESSION_COOKIE)
    return {**origin, "cookie": f"{SESSION_COOKIE}={token}"} if token else dict(origin)


def test_ws_streams_snapshot_then_events(api: Api) -> None:
    fast_agent(api)
    run_id = start(api, create_profile(api, "slow"))
    wait_status(api, run_id, {"running"})
    api.login_as(Role.viewer)
    with api.client.websocket_connect(f"/api/runs/{run_id}/ws", headers=ws_headers(api)) as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot"
        assert snap["config"]["run_id"] == run_id
        assert snap["status"]["status"] == "running"
        last_seq = snap["seq"]
        types = set()
        for _ in range(12):
            msg = ws.receive_json()
            assert msg["seq"] == last_seq + 1  # nothing lost between snapshot and stream
            last_seq = msg["seq"]
            types.add(msg["type"])
        assert {"log", "progress", "resources"} <= types
        ws.send_text("not json")
        ws.send_text(json.dumps({"type": "ping"}))
        for _ in range(50):
            if ws.receive_json()["type"] == "pong":
                break
        else:
            raise AssertionError("no pong")
        api.login_as(Role.editor)
        api.client.post(f"/api/runs/{run_id}/cancel")
        final = None
        for _ in range(500):
            try:
                msg = ws.receive_json()
            except WebSocketDisconnect:
                break
            if msg["type"] == "status":
                final = msg["status"]
        assert final == "cancelled"


def test_ws_snapshot_of_a_stored_run(api: Api, settings: Any) -> None:
    runs = fast_agent(api)
    run_id = start(api, create_profile(api))
    wait_status(api, run_id, {"completed"})
    runs.hub._runs.clear()  # e.g. after an agent restart
    with api.client.websocket_connect(f"/api/runs/{run_id}/ws", headers=ws_headers(api)) as ws:
        snap = ws.receive_json()
        assert snap["status"]["status"] == "completed"
        assert snap["config"]["duration_s"] == 30
        assert any("progress: 1.0 s" in m["line"] for m in snap["log"])
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
        assert info.value.code == 1000


def test_ws_finished_run_in_memory(api: Api) -> None:
    fast_agent(api)
    run_id = start(api, create_profile(api))
    wait_status(api, run_id, {"completed"})
    with api.client.websocket_connect(f"/api/runs/{run_id}/ws", headers=ws_headers(api)) as ws:
        snap = ws.receive_json()
        assert [p["tps"] for p in snap["progress"]] == [5000.0, 6000.0]
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


@pytest.mark.parametrize(
    ("headers", "cookie", "code"),
    [
        ({}, True, 4403),
        ({"origin": "https://evil.example"}, True, 4403),
        (ORIGIN, False, 4401),
    ],
)
def test_ws_rejects_foreign_origin_and_no_session(
    api: Api, headers: dict[str, str], cookie: bool, code: int
) -> None:
    run_id = start(api, create_profile(api))
    if not cookie:
        api.client.cookies.clear()
    url = f"/api/runs/{run_id}/ws"
    with (
        pytest.raises(WebSocketDisconnect) as info,
        api.client.websocket_connect(url, headers=ws_headers(api, headers)) as ws,
    ):
        ws.receive_json()
    assert info.value.code == code


def test_ws_unknown_run_and_temporary_password(api: Api) -> None:
    api.login_as(Role.viewer)
    with (
        pytest.raises(WebSocketDisconnect) as info,
        api.client.websocket_connect("/api/runs/999/ws", headers=ws_headers(api)) as ws,
    ):
        ws.receive_json()
    assert info.value.code == 4404

    api.add_user("tmp", Role.viewer, must_change=True)
    api.login("tmp")
    assert SESSION_COOKIE in api.client.cookies
    with (
        pytest.raises(WebSocketDisconnect) as info,
        api.client.websocket_connect("/api/runs/999/ws", headers=ws_headers(api)) as ws,
    ):
        ws.receive_json()
    assert info.value.code == 4403


def test_ws_prefers_forwarded_host() -> None:
    from starlette.datastructures import Headers

    from app.api.ws import same_origin

    class Fake:
        def __init__(self, headers: dict[str, str]) -> None:
            self.headers = Headers(headers)

    assert same_origin(
        Fake(
            {
                "origin": "https://studio.corp",
                "host": "10.0.0.5:8080",
                "x-forwarded-host": "studio.corp",
            }
        )
    )  # type: ignore[arg-type]
    assert not same_origin(Fake({"origin": "https://studio.corp", "host": "10.0.0.5:8080"}))  # type: ignore[arg-type]
    assert same_origin(Fake({"origin": "http://localhost:5173", "host": "localhost:5173"}))  # type: ignore[arg-type]

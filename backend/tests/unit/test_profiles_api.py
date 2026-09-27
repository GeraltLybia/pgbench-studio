from __future__ import annotations

import time
from typing import Any

import pytest
from sqlalchemy import select

from app.core.connection import failure
from app.core.healthchecks import CheckResult
from app.storage.crypto import SecretBox
from app.storage.models import Profile, Role
from tests.conftest import FACTS, Api

BODY: dict[str, Any] = {
    "name": "stage-db · bench",
    "host": "stage-db.internal",
    "port": 5432,
    "dbname": "bench",
    "user": "bench_runner",
    "sslmode": "require",
    "app_name": "pgbench-studio",
    "connect_timeout_s": 10,
    "password": "db-secret-1",
}


def editor(api: Api) -> None:
    api.login_as(Role.editor)


def create(api: Api, **overrides: Any) -> dict[str, Any]:
    resp = api.client.post("/api/profiles", json={**BODY, **overrides})
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def stored(api: Api, profile_id: int) -> Profile:
    async def get(db: Any) -> Profile:
        return (await db.execute(select(Profile).where(Profile.id == profile_id))).scalar_one()

    profile: Profile = api.db_call(get)
    return profile


def test_create_list_and_password_encrypted(api: Api) -> None:
    editor(api)
    profile = create(api)
    assert profile["has_password"] is True
    assert "password" not in profile and "password_enc" not in profile
    assert "db-secret-1" not in api.client.get("/api/profiles").text

    row = stored(api, profile["id"])
    assert row.password_enc is not None and "db-secret-1" not in row.password_enc
    box: SecretBox = api.client.app.state.secret_box  # type: ignore[attr-defined]
    assert box.decrypt(row.password_enc) == "db-secret-1"

    api.login_as(Role.viewer)
    listed = api.client.get("/api/profiles").json()
    assert [p["name"] for p in listed] == ["stage-db · bench"]


def test_create_without_password(api: Api) -> None:
    editor(api)
    assert create(api, password=None)["has_password"] is False


def test_duplicate_and_invalid(api: Api) -> None:
    editor(api)
    create(api)
    assert api.client.post("/api/profiles", json=BODY).status_code == 409
    for bad in (
        {"host": "bad host"},
        {"host": "a,b"},
        {"port": 0},
        {"sslmode": "allow"},
        {"connect_timeout_s": 0},
        {"dbname": ""},
        {"app_name": "тест"},
    ):
        resp = api.client.post("/api/profiles", json={**BODY, "name": "x", **bad})
        assert resp.status_code == 422, bad


def test_update_keeps_replaces_and_clears_password(api: Api) -> None:
    editor(api)
    profile = create(api)
    pid = profile["id"]
    box: SecretBox = api.client.app.state.secret_box  # type: ignore[attr-defined]
    update = {k: v for k, v in BODY.items() if k != "password"}

    resp = api.client.put(f"/api/profiles/{pid}", json={**update, "host": "other"})
    assert resp.json()["host"] == "other"
    assert box.decrypt(stored(api, pid).password_enc or "") == "db-secret-1"

    api.client.put(f"/api/profiles/{pid}", json={**update, "password": "new-secret"})
    assert box.decrypt(stored(api, pid).password_enc or "") == "new-secret"

    resp = api.client.put(f"/api/profiles/{pid}", json={**update, "clear_password": True})
    assert resp.json()["has_password"] is False

    create(api, name="second")
    assert (
        api.client.put(f"/api/profiles/{pid}", json={**update, "name": "second"}).status_code == 409
    )
    assert api.client.put("/api/profiles/999", json=update).status_code == 404


def test_delete(api: Api) -> None:
    editor(api)
    pid = create(api)["id"]
    assert api.client.delete(f"/api/profiles/{pid}").status_code == 204
    assert api.client.delete(f"/api/profiles/{pid}").status_code == 404
    assert api.client.get("/api/profiles").json() == []


def checker(api: Api) -> Any:
    return api.client.app.state.connection_checker  # type: ignore[attr-defined]


def test_connection_check_success(api: Api) -> None:
    editor(api)
    form = {k: v for k, v in BODY.items() if k != "name"}
    resp = api.client.post("/api/profiles/test", json=form)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["server_major"] == 18
    assert body["pgbench_version"] == "18.1"
    assert body["warnings"] == []
    assert body["free_connections"] == 184
    assert body["scale"] == 100
    assert checker(api).calls[-1].password == "db-secret-1"
    assert "db-secret-1" not in resp.text


def test_connection_check_uses_stored_password(api: Api) -> None:
    editor(api)
    pid = create(api)["id"]
    form = {k: v for k, v in BODY.items() if k not in ("name", "password")}
    api.client.post("/api/profiles/test", json={**form, "profile_id": pid})
    assert checker(api).calls[-1].password == "db-secret-1"
    # An explicit password from the form wins over the stored one.
    api.client.post("/api/profiles/test", json={**form, "profile_id": pid, "password": "typed"})
    assert checker(api).calls[-1].password == "typed"
    api.client.post("/api/profiles/test", json=form)
    assert checker(api).calls[-1].password is None
    assert (
        api.client.post("/api/profiles/test", json={**form, "profile_id": 999}).status_code == 404
    )


def test_connection_check_undecryptable_password(api: Api) -> None:
    editor(api)
    pid = create(api)["id"]

    async def corrupt(db: Any) -> None:
        (await db.get(Profile, pid)).password_enc = "not-a-token"

    api.db_call(corrupt)
    form = {k: v for k, v in BODY.items() if k not in ("name", "password")}
    resp = api.client.post("/api/profiles/test", json={**form, "profile_id": pid})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "password_undecryptable"


@pytest.mark.parametrize(
    ("code", "raw"),
    [
        ("auth_failed", 'FATAL:  password authentication failed for user "bench_runner"'),
        ("host_unreachable", "could not translate host name"),
        ("timeout", "timeout expired"),
        ("connection_refused", "Connection refused"),
        ("database_not_found", 'database "bench" does not exist'),
        ("no_connect_privilege", 'permission denied for database "bench"'),
        ("ssl_error", "server does not support SSL"),
        ("unknown", "odd"),
    ],
)
def test_connection_check_failure(api: Api, code: str, raw: str) -> None:
    editor(api)
    checker(api).result = failure(code, raw)
    form = {k: v for k, v in BODY.items() if k != "name"}
    body = api.client.post("/api/profiles/test", json=form).json()
    assert body["ok"] is False
    assert body["code"] == code
    assert body["message"] and body["hint"]
    assert body["raw"] == raw


def test_connection_check_version_warning(api: Api) -> None:
    import dataclasses

    editor(api)
    checker(api).result = dataclasses.replace(FACTS, server_version_num=120022)
    form = {k: v for k, v in BODY.items() if k != "name"}
    body = api.client.post("/api/profiles/test", json=form).json()
    assert body["ok"] is True
    assert len(body["warnings"]) == 1


# --- pgbench -i ---------------------------------------------------------------------------

INIT = {"scale": 1, "fillfactor": 100, "foreign_keys": True, "unlogged": False}


def wait_finished(api: Api, run_id: int, timeout: float = 10) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body: dict[str, Any] = api.client.get(f"/api/runs/{run_id}").json()
        if body["status"] in ("completed", "failed", "cancelled"):
            return body
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_init_runs_pgbench_and_reports_progress(api: Api) -> None:
    editor(api)
    pid = create(api)["id"]
    resp = api.client.post(f"/api/profiles/{pid}/init", json={**INIT, "confirm_dbname": "bench"})
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    body = wait_finished(api, run_id)
    assert body["status"] == "completed"
    assert body["kind"] == "init"
    assert body["started_by"] == "user-editor"
    assert body["server_version"] == "18.0"
    assert body["argv"][1:] == ["-i", "-s", "1", "-F", "100", "--foreign-keys"]
    assert any("creating primary keys" in line["line"] for line in body["log_tail"])
    assert body["progress"] is None
    assert checker(api).calls[-1].password == "db-secret-1"

    api.login_as(Role.viewer)
    assert api.client.get(f"/api/runs/{run_id}").status_code == 200


def test_init_progress_while_running(api: Api) -> None:
    editor(api)
    pid = create(api, dbname="slow")["id"]
    run_id = api.client.post(
        f"/api/profiles/{pid}/init", json={**INIT, "confirm_dbname": "slow"}
    ).json()["run_id"]
    deadline = time.monotonic() + 5
    body: dict[str, Any] = {}
    while time.monotonic() < deadline:
        body = api.client.get(f"/api/runs/{run_id}").json()
        if body["log_tail"]:
            break
        time.sleep(0.05)
    assert body["status"] == "running"
    assert body["progress"]["phase"] == "Удаление старых таблиц"

    busy = api.client.post(f"/api/profiles/{pid}/init", json={**INIT, "confirm_dbname": "slow"})
    assert busy.status_code == 409
    assert busy.json()["detail"]["code"] == "agent_busy"


def test_init_failure_is_reported(api: Api) -> None:
    editor(api)
    pid = create(api, dbname="failme")["id"]
    run_id = api.client.post(
        f"/api/profiles/{pid}/init", json={**INIT, "confirm_dbname": "failme"}
    ).json()["run_id"]
    body = wait_finished(api, run_id)
    assert body["status"] == "failed"
    assert "boom" in body["error"]


def test_init_guards(api: Api) -> None:
    editor(api)
    pid = create(api)["id"]
    url = f"/api/profiles/{pid}/init"

    wrong = api.client.post(url, json={**INIT, "confirm_dbname": "other"})
    assert (wrong.status_code, wrong.json()["detail"]["code"]) == (422, "confirm_mismatch")

    over = api.client.post(url, json={**INIT, "scale": 5001, "confirm_dbname": "bench"})
    assert (over.status_code, over.json()["detail"]["code"]) == (422, "scale_limit")

    large = {**INIT, "scale": 4000, "confirm_dbname": "bench"}
    resp = api.client.post(url, json=large)
    assert (resp.status_code, resp.json()["detail"]["code"]) == (422, "large_data_unconfirmed")

    assert (
        api.client.post(url, json={**INIT, "fillfactor": 5, "confirm_dbname": "bench"}).status_code
        == 422
    )
    assert (
        api.client.post(
            "/api/profiles/999/init", json={**INIT, "confirm_dbname": "bench"}
        ).status_code
        == 404
    )


def test_init_repeats_connection_check(api: Api) -> None:
    editor(api)
    pid = create(api)["id"]
    checker(api).result = failure("auth_failed", "password authentication failed")
    resp = api.client.post(f"/api/profiles/{pid}/init", json={**INIT, "confirm_dbname": "bench"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "auth_failed"
    assert detail["ok"] is False
    assert detail["hint"] and detail["raw"]


def test_init_blocked_by_failed_health_check(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    editor(api)
    pid = create(api)["id"]
    health = api.client.app.state.health  # type: ignore[attr-defined]

    async def broken() -> list[CheckResult]:
        return [CheckResult("disk", "Свободное место", True, "fail", "мало места")]

    monkeypatch.setattr(health, "_collect", broken)
    health._cached = None
    resp = api.client.post(f"/api/profiles/{pid}/init", json={**INIT, "confirm_dbname": "bench"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["failed"] == ["Свободное место"]


def test_run_not_found(api: Api) -> None:
    api.login_as(Role.viewer)
    assert api.client.get("/api/runs/999").status_code == 404

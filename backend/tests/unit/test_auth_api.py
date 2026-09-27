from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import Settings
from app.main import create_app
from app.security.sessions import SESSION_COOKIE
from app.storage.models import Role, User, utcnow
from tests.conftest import ADMIN, ADMIN_PASSWORD, PASSWORD, Api


def test_first_admin_is_bootstrapped(api: Api) -> None:
    resp = api.login(ADMIN, ADMIN_PASSWORD)
    assert resp.status_code == 200
    assert resp.json() == {
        "id": 1,
        "username": ADMIN,
        "role": "admin",
        "must_change_password": False,
    }


def test_login_sets_secure_cookie(api: Api) -> None:
    api.add_user("ed", Role.editor)
    resp = api.login("ed")
    cookie = resp.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=strict" in cookie
    assert "Max-Age=43200" in cookie
    me = api.client.get("/api/auth/me")
    assert me.json()["username"] == "ed"
    assert me.json()["role"] == "editor"
    user = api.get_user("ed")
    assert user.last_login_at is not None
    assert user.last_login_ip == "testclient"


def test_wrong_password_reports_attempts_left(api: Api) -> None:
    api.add_user("ed", Role.editor)
    resp = api.login("ed", "wrong")
    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_credentials"
    assert detail["attempts_left"] == 4
    assert detail["lockout_min"] == 5
    assert SESSION_COOKIE not in resp.cookies


def test_unknown_user_is_indistinguishable(api: Api) -> None:
    resp = api.login("ghost", "whatever")
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "invalid_credentials"


def test_user_lockout_after_max_failures(api: Api) -> None:
    api.add_user("ed", Role.editor)
    guard = api.client.app.state.login_guard  # type: ignore[attr-defined]
    for _ in range(4):
        assert api.login("ed", "wrong").status_code == 401
        guard.register_success("testclient")  # isolate the per-login counter
    resp = api.login("ed", "wrong")
    assert resp.status_code == 429
    assert resp.json()["detail"]["code"] == "login_locked"
    assert int(resp.headers["retry-after"]) == 300
    # Even the right password is rejected while locked.
    guard.register_success("testclient")
    assert api.login("ed").status_code == 429

    async def expire(db, user_id):  # type: ignore[no-untyped-def]
        user = await db.get(User, user_id)
        user.locked_until = utcnow() - timedelta(seconds=1)

    api.db_call(expire, api.get_user("ed").id)
    assert api.login("ed").status_code == 200
    assert api.get_user("ed").failed_attempts == 0


def test_ip_lockout_spans_logins(api: Api) -> None:
    api.add_user("ed", Role.editor)
    for i in range(4):
        assert api.login(f"ghost{i}", "x").status_code == 401
    assert api.login("ghost5", "x").status_code == 429
    resp = api.login("ed")
    assert resp.status_code == 429


def test_disabled_user_cannot_login(api: Api) -> None:
    api.add_user("ed", Role.editor)

    async def disable(db, user_id):  # type: ignore[no-untyped-def]
        (await db.get(User, user_id)).disabled = True

    api.db_call(disable, api.get_user("ed").id)
    resp = api.login("ed")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "user_disabled"


def test_session_of_disabled_user_is_revoked(api: Api) -> None:
    api.add_user("ed", Role.editor)
    api.login("ed")

    async def disable(db, user_id):  # type: ignore[no-untyped-def]
        (await db.get(User, user_id)).disabled = True

    api.db_call(disable, api.get_user("ed").id)
    assert api.client.get("/api/auth/me").status_code == 401


def test_expired_session_is_rejected(api: Api) -> None:
    from sqlalchemy import update

    from app.storage.models import Session

    api.add_user("ed", Role.editor)
    api.login("ed")

    async def expire(db):  # type: ignore[no-untyped-def]
        await db.execute(update(Session).values(expires_at=utcnow() - timedelta(seconds=1)))

    api.db_call(expire)
    assert api.client.get("/api/auth/me").status_code == 401


def test_logout(api: Api) -> None:
    api.add_user("ed", Role.editor)
    api.login("ed")
    token = api.client.cookies[SESSION_COOKIE]
    assert api.client.post("/api/auth/logout").status_code == 204
    api.client.cookies.set(SESSION_COOKIE, token)
    assert api.client.get("/api/auth/me").status_code == 401


def test_temporary_password_must_be_changed(api: Api) -> None:
    api.add_user("tmp", Role.editor, must_change=True)
    resp = api.login("tmp")
    assert resp.json()["must_change_password"] is True
    assert api.client.get("/api/auth/me").status_code == 200
    blocked = api.client.get("/api/system/info")
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "password_change_required"

    wrong = api.client.post(
        "/api/auth/password", json={"current_password": "nope", "new_password": "brand-new-1"}
    )
    assert wrong.status_code == 403
    same = api.client.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": PASSWORD}
    )
    assert same.status_code == 422
    short = api.client.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": "short"}
    )
    assert short.status_code == 422

    ok = api.client.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": "brand-new-1"}
    )
    assert ok.status_code == 200
    assert ok.json()["must_change_password"] is False
    assert api.client.get("/api/system/info").status_code == 200
    assert api.login("tmp", "brand-new-1").status_code == 200


def test_password_change_revokes_other_sessions(api: Api) -> None:
    api.add_user("ed", Role.editor)
    api.login("ed")
    other_token = api.client.cookies[SESSION_COOKIE]
    api.login("ed")
    resp = api.client.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": "brand-new-1"}
    )
    assert resp.status_code == 200
    assert api.client.get("/api/auth/me").status_code == 200
    api.client.cookies.set(SESSION_COOKIE, other_token)
    assert api.client.get("/api/auth/me").status_code == 401


def test_plain_http_mutations_are_rejected(settings: Settings, secret_env: str) -> None:
    with TestClient(create_app(settings), base_url="http://testserver") as client:
        resp = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASSWORD})
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "https_required"
        assert client.get("/healthz").status_code == 200


def test_dev_mode_allows_plain_http(
    make_settings: Callable[..., Settings], secret_env: str
) -> None:
    settings = make_settings(server={"dev_mode": True}, auth={"cookie_secure": False})
    with TestClient(create_app(settings), base_url="http://testserver") as client:
        resp = client.post("/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASSWORD})
        assert resp.status_code == 200
        assert "Secure" not in resp.headers["set-cookie"]


@pytest.fixture
def proxied(settings: Settings, secret_env: str) -> Iterator[TestClient]:
    """The app behind uvicorn's proxy-header handling, trusting only the test peer."""
    app = create_app(settings)
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts=["testclient"])
    with TestClient(wrapped, base_url="http://testserver") as client:  # type: ignore[arg-type]
        client.app_state = app.state  # type: ignore[attr-defined]
        yield client


def test_balancer_headers_give_https_and_real_ip(proxied: TestClient) -> None:
    headers = {"X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.7"}
    resp = proxied.post(
        "/api/auth/login", json={"username": ADMIN, "password": ADMIN_PASSWORD}, headers=headers
    )
    assert resp.status_code == 200

    async def last_ip() -> str | None:
        from app.storage import repo

        async with proxied.app_state.sessionmaker() as db:  # type: ignore[attr-defined]
            user = await repo.get_user_by_username(db, ADMIN)
            return user.last_login_ip if user else None

    assert proxied.portal.call(last_ip) == "203.0.113.7"  # type: ignore[union-attr]


def test_lockout_counts_real_client_ip(proxied: TestClient) -> None:
    def attempt(ip: str) -> int:
        return proxied.post(
            "/api/auth/login",
            json={"username": "ghost", "password": "x"},
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": ip},
        ).status_code

    for _ in range(4):
        assert attempt("203.0.113.7") == 401
    assert attempt("203.0.113.7") == 429
    # Another client behind the same balancer is not affected.
    assert attempt("198.51.100.1") == 401

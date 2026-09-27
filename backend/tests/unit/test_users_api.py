from __future__ import annotations

import pytest

from app.security.sessions import SESSION_COOKIE
from app.storage import repo
from app.storage.models import Role
from tests.conftest import ADMIN, ADMIN_PASSWORD, Api


def login_admin(api: Api) -> None:
    assert api.login(ADMIN, ADMIN_PASSWORD).status_code == 200


def test_create_user_with_temporary_password(api: Api) -> None:
    login_admin(api)
    resp = api.client.post("/api/users", json={"username": "viewer.one", "role": "viewer"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["user"]["role"] == "viewer"
    assert body["user"]["must_change_password"] is True
    temp = body["temporary_password"]

    listed = api.client.get("/api/users").json()
    assert [u["username"] for u in listed] == [ADMIN, "viewer.one"]
    assert "password_hash" not in listed[0]

    resp = api.login("viewer.one", temp)
    assert resp.json()["must_change_password"] is True


def test_duplicate_and_invalid_username(api: Api) -> None:
    login_admin(api)
    assert (
        api.client.post("/api/users", json={"username": ADMIN, "role": "viewer"}).status_code == 409
    )
    assert (
        api.client.post("/api/users", json={"username": "a b", "role": "viewer"}).status_code == 422
    )
    assert api.client.post("/api/users", json={"username": "ok", "role": "root"}).status_code == 422


def test_change_role_and_disable(api: Api) -> None:
    ed = api.add_user("ed", Role.editor)
    api.login("ed")
    ed_token = api.client.cookies[SESSION_COOKIE]

    login_admin(api)
    resp = api.client.patch(f"/api/users/{ed.id}", json={"role": "viewer"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "viewer"

    resp = api.client.patch(f"/api/users/{ed.id}", json={"disabled": True})
    assert resp.json()["disabled"] is True
    admin_token = api.client.cookies[SESSION_COOKIE]

    api.client.cookies.set(SESSION_COOKIE, ed_token)
    assert api.client.get("/api/auth/me").status_code == 401
    assert api.login("ed").status_code == 403

    api.client.cookies.set(SESSION_COOKIE, admin_token)
    resp = api.client.patch(f"/api/users/{ed.id}", json={"disabled": False})
    assert resp.json()["disabled"] is False
    assert api.login("ed").status_code == 200


def test_last_admin_is_protected(api: Api) -> None:
    login_admin(api)
    admin_id = api.get_user(ADMIN).id
    resp = api.client.patch(f"/api/users/{admin_id}", json={"role": "editor"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "self_demote"
    resp = api.client.patch(f"/api/users/{admin_id}", json={"disabled": True})
    assert resp.json()["detail"]["code"] == "self_disable"

    other = api.add_user("second", Role.admin)
    # Two active admins: one may be demoted, but then the remaining one is protected.
    assert api.client.patch(f"/api/users/{other.id}", json={"role": "editor"}).status_code == 200
    third = api.add_user("third", Role.admin)
    assert api.client.patch(f"/api/users/{third.id}", json={"disabled": True}).status_code == 200


def test_cannot_remove_last_active_admin_from_another_admin(api: Api) -> None:
    other = api.add_user("second", Role.admin)
    login_admin(api)
    admin_id = api.get_user(ADMIN).id
    # Disable the bootstrapped admin via the other admin, leaving `second` as the only one.
    api.login("second")
    assert api.client.patch(f"/api/users/{admin_id}", json={"disabled": True}).status_code == 200
    # `second` cannot demote itself, and nobody else is an active admin.
    resp = api.client.patch(f"/api/users/{other.id}", json={"role": "viewer"})
    assert resp.json()["detail"]["code"] == "self_demote"


def test_disabled_admin_can_be_demoted(api: Api) -> None:
    login_admin(api)
    ghost = api.add_user("ghost-admin", Role.admin)
    assert api.client.patch(f"/api/users/{ghost.id}", json={"disabled": True}).status_code == 200
    assert api.client.patch(f"/api/users/{ghost.id}", json={"role": "viewer"}).status_code == 200


def test_last_active_admin_guard(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    """Defence in depth: the count check holds even if the caller is not counted (e.g. a race)."""
    other = api.add_user("second", Role.admin)
    login_admin(api)

    async def one(_db: object) -> int:
        return 1

    monkeypatch.setattr(repo, "count_active_admins", one)
    resp = api.client.patch(f"/api/users/{other.id}", json={"disabled": True})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "last_admin"


def test_reset_password(api: Api) -> None:
    ed = api.add_user("ed", Role.editor)
    login_admin(api)
    resp = api.client.post(f"/api/users/{ed.id}/reset-password")
    assert resp.status_code == 200
    temp = resp.json()["temporary_password"]
    assert resp.json()["user"]["must_change_password"] is True
    assert api.login("ed").status_code == 401
    assert api.login("ed", temp).json()["must_change_password"] is True


def test_unknown_user(api: Api) -> None:
    login_admin(api)
    assert api.client.patch("/api/users/999", json={"role": "viewer"}).status_code == 404
    assert api.client.post("/api/users/999/reset-password").status_code == 404

"""Permission matrix: every endpoint under no session, viewer, editor and admin."""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.main import create_app
from app.storage.models import Role
from tests.conftest import Api

PUBLIC = {("GET", "/healthz"), ("GET", "/readyz"), ("POST", "/api/auth/login")}

# (method, path, body, minimal role). Paths use id 1 — the bootstrapped admin always exists.
ENDPOINTS: list[tuple[str, str, dict[str, Any] | None, Role]] = [
    ("GET", "/api/auth/me", None, Role.viewer),
    ("POST", "/api/auth/logout", None, Role.viewer),
    (
        "POST",
        "/api/auth/password",
        {"current_password": "wrong", "new_password": "whatever-123"},
        Role.viewer,
    ),
    ("GET", "/api/system/health", None, Role.viewer),
    ("GET", "/api/system/info", None, Role.viewer),
    ("GET", "/api/users", None, Role.admin),
    ("POST", "/api/users", {"username": "newbie", "role": "viewer"}, Role.admin),
    ("PATCH", "/api/users/1", {"role": "admin"}, Role.admin),
    ("POST", "/api/users/1/reset-password", None, Role.admin),
]

ROLES: list[Role | None] = [None, Role.viewer, Role.editor, Role.admin]


def test_matrix_covers_every_route(settings: Settings) -> None:
    schema = create_app(settings).openapi()
    routes = {(method.upper(), path) for path, item in schema["paths"].items() for method in item}
    listed = {(m, p.replace("/1", "/{user_id}")) for m, p, _, _ in ENDPOINTS}
    assert routes - PUBLIC == listed


@pytest.mark.parametrize("role", ROLES, ids=lambda r: r.value if r else "anonymous")
@pytest.mark.parametrize(
    ("method", "path", "body", "required"), ENDPOINTS, ids=[f"{m} {p}" for m, p, _, _ in ENDPOINTS]
)
def test_permission_matrix(
    api: Api,
    role: Role | None,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    required: Role,
) -> None:
    api.login_as(role)
    resp = api.client.request(method, path, json=body)
    if role is None:
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "not_authenticated"
    elif not role.allows(required):
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "forbidden"
    else:
        assert resp.status_code not in (401,)
        if resp.status_code == 403:
            # Allowed by role; rejected only by business rules (e.g. wrong current password).
            assert resp.json()["detail"]["code"] != "forbidden"


@pytest.mark.parametrize("path", ["/healthz", "/readyz"])
def test_public_probes(api: Api, path: str) -> None:
    api.login_as(None)
    assert api.client.get(path).status_code == 200


def test_role_hierarchy() -> None:
    assert Role.admin.allows(Role.editor)
    assert Role.editor.allows(Role.viewer)
    assert not Role.viewer.allows(Role.editor)
    assert not Role.editor.allows(Role.admin)

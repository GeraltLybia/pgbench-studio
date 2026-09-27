"""Permission matrix: every endpoint under no session, viewer, editor and admin."""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.main import create_app
from app.storage.models import Role
from tests.conftest import Api

PUBLIC = {("GET", "/healthz"), ("GET", "/readyz"), ("POST", "/api/auth/login")}

PROFILE = {
    "name": "p",
    "host": "db",
    "dbname": "bench",
    "user": "u",
}

RUN = {
    "profile_id": 1,
    "duration_s": 60,
    "scenarios": [{"kind": "builtin", "name": "select-only"}],
}
DRY = {"profile_id": 1, "scenario": {"kind": "builtin", "name": "select-only"}}

# (method, path, body, minimal role). Paths use id 1 — the bootstrapped admin always exists;
# a missing profile or run answers 404, which still proves the role check passed.
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
    ("GET", "/api/profiles", None, Role.viewer),
    ("POST", "/api/profiles", PROFILE, Role.editor),
    ("PUT", "/api/profiles/1", PROFILE, Role.editor),
    ("DELETE", "/api/profiles/1", None, Role.editor),
    ("POST", "/api/profiles/test", {"host": "db", "dbname": "b", "user": "u"}, Role.editor),
    ("POST", "/api/profiles/1/init", {"scale": 1, "confirm_dbname": "x"}, Role.editor),
    ("GET", "/api/runs/1", None, Role.viewer),
    ("GET", "/api/scripts", None, Role.viewer),
    ("POST", "/api/scripts", {"name": "s.sql", "body": "SELECT 1;"}, Role.editor),
    ("PUT", "/api/scripts/1", {"name": "s.sql", "body": "SELECT 1;"}, Role.editor),
    ("DELETE", "/api/scripts/1", None, Role.editor),
    ("POST", "/api/scripts/validate", {"body": "SELECT 1;"}, Role.viewer),
    ("GET", "/api/builtins", None, Role.viewer),
    ("POST", "/api/runs/preview", RUN, Role.editor),
    ("POST", "/api/runs/dry", DRY, Role.editor),
    ("POST", "/api/runs", RUN, Role.editor),
]

TEMPLATES = {
    "/api/users/1": "/api/users/{user_id}",
    "/api/users/1/reset-password": "/api/users/{user_id}/reset-password",
    "/api/profiles/1": "/api/profiles/{profile_id}",
    "/api/profiles/1/init": "/api/profiles/{profile_id}/init",
    "/api/runs/1": "/api/runs/{run_id}",
    "/api/scripts/1": "/api/scripts/{script_id}",
}

ROLES: list[Role | None] = [None, Role.viewer, Role.editor, Role.admin]


def test_matrix_covers_every_route(settings: Settings) -> None:
    schema = create_app(settings).openapi()
    routes = {(method.upper(), path) for path, item in schema["paths"].items() for method in item}
    listed = {(m, TEMPLATES.get(p, p)) for m, p, _, _ in ENDPOINTS}
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

"""Connection profiles, connection check and `pgbench -i`."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Body, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbDep, EditorDep, SettingsDep, ViewerDep, client_ip
from app.api.errors import api_error
from app.core.command import LARGE_INIT_BYTES, InitOptions, estimate_init_bytes
from app.core.connection import (
    ConnFailure,
    ConnParams,
    ServerFacts,
    compatibility_warnings,
)
from app.core.healthchecks import HealthService
from app.core.runner import RunLimitError, RunManager
from app.schemas import (
    ConnectionFields,
    ConnectionTestFail,
    ConnectionTestOk,
    ConnectionTestRequest,
    ErrorResponse,
    InitRequest,
    ProfileCreate,
    ProfileOut,
    ProfileUpdate,
    RunStarted,
)
from app.storage.crypto import DecryptionError, SecretBox
from app.storage.models import Profile, utcnow

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profiles", tags=["profiles"])

Checker = Callable[[ConnParams], Awaitable[ServerFacts | ConnFailure]]

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
}


def _box(request: Request) -> SecretBox:
    box: SecretBox = request.app.state.secret_box
    return box


def _to_out(profile: Profile) -> ProfileOut:
    return ProfileOut(
        id=profile.id,
        name=profile.name,
        host=profile.host,
        port=profile.port,
        dbname=profile.dbname,
        user=profile.user,
        sslmode=profile.sslmode,
        app_name=profile.app_name,
        connect_timeout_s=profile.connect_timeout_s,
        has_password=profile.password_enc is not None,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _params(fields: ConnectionFields, password: str | None) -> ConnParams:
    return ConnParams(
        host=fields.host,
        port=fields.port,
        dbname=fields.dbname,
        user=fields.user,
        sslmode=fields.sslmode,
        app_name=fields.app_name,
        connect_timeout_s=fields.connect_timeout_s,
        password=password,
    )


def _stored_password(box: SecretBox, profile: Profile) -> str | None:
    if profile.password_enc is None:
        return None
    try:
        return box.decrypt(profile.password_enc)
    except DecryptionError as exc:
        raise api_error(
            409,
            "password_undecryptable",
            "Сохранённый пароль не расшифровывается текущим ключом. Введите пароль заново.",
        ) from exc


async def get_profile_or_404(db: DbDep, profile_id: int) -> Profile:
    profile = await db.get(Profile, profile_id)
    if profile is None:
        raise api_error(404, "profile_not_found", "Профиль не найден")
    return profile


def profile_params(request: Request, profile: Profile) -> ConnParams:
    """Connection parameters of a saved profile with its decrypted password."""
    return _params(
        ConnectionFields.model_validate(profile, from_attributes=True),
        _stored_password(_box(request), profile),
    )


async def require_ready_agent(request: Request) -> None:
    """503 when a required health check fails: no pgbench is started then."""
    health: HealthService = request.app.state.health
    _, checks = await health.results()
    failed = [c.title for c in checks if c.required and c.status == "fail"]
    if failed:
        raise api_error(
            503,
            "agent_not_ready",
            "Запуск заблокирован: не пройдены обязательные проверки агента: " + ", ".join(failed),
            failed=failed,
        )


def _pgbench_major(request: Request) -> tuple[str | None, int | None]:
    health: HealthService = request.app.state.health
    version = health.pgbench_version
    return version, int(version.split(".")[0]) if version else None


async def run_check(request: Request, params: ConnParams) -> ConnectionTestOk | ConnectionTestFail:
    checker: Checker = request.app.state.connection_checker
    health: HealthService = request.app.state.health
    if health.pgbench_version is None:
        await health.results()
    result = await checker(params)
    now = utcnow()
    if isinstance(result, ConnFailure):
        return ConnectionTestFail(
            checked_at=now,
            code=result.code,
            message=result.message,
            hint=result.hint,
            raw=result.raw,
        )
    version, major = _pgbench_major(request)
    return ConnectionTestOk(
        checked_at=now,
        server_version=result.server_version,
        server_version_num=result.server_version_num,
        server_major=result.server_major,
        pgbench_version=version,
        warnings=compatibility_warnings(result.server_major, major),
        response_ms=result.response_ms,
        max_connections=result.max_connections,
        reserved_connections=result.reserved_connections,
        used_connections=result.used_connections,
        free_connections=result.free_connections,
        pgbench_tables=result.pgbench_tables,
        scale=result.scale,
        accounts_rows=result.accounts_rows,
    )


@router.get("", response_model=list[ProfileOut], responses=_ERRORS)
async def list_profiles(db: DbDep, _user: ViewerDep) -> list[ProfileOut]:
    result = await db.execute(select(Profile).order_by(Profile.name))
    return [_to_out(p) for p in result.scalars()]


@router.post(
    "",
    response_model=ProfileOut,
    status_code=201,
    responses={**_ERRORS, 409: {"model": ErrorResponse}},
)
async def create_profile(
    body: ProfileCreate, request: Request, db: DbDep, user: EditorDep
) -> ProfileOut:
    profile = Profile(
        **body.model_dump(exclude={"password"}),
        password_enc=_box(request).encrypt(body.password) if body.password is not None else None,
    )
    db.add(profile)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise api_error(409, "profile_exists", "Профиль с таким именем уже есть") from exc
    log.info(
        "profile created",
        extra={"ip": client_ip(request), "username": user.username, "profile": profile.name},
    )
    return _to_out(profile)


@router.put(
    "/{profile_id}",
    response_model=ProfileOut,
    responses={**_ERRORS, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def update_profile(
    profile_id: int, body: ProfileUpdate, request: Request, db: DbDep, user: EditorDep
) -> ProfileOut:
    profile = await get_profile_or_404(db, profile_id)
    for key, value in body.model_dump(exclude={"password", "clear_password"}).items():
        setattr(profile, key, value)
    if body.password is not None:
        profile.password_enc = _box(request).encrypt(body.password)
    elif body.clear_password:
        profile.password_enc = None
    profile.updated_at = utcnow()
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise api_error(409, "profile_exists", "Профиль с таким именем уже есть") from exc
    log.info(
        "profile updated",
        extra={"ip": client_ip(request), "username": user.username, "profile": profile.name},
    )
    return _to_out(profile)


@router.delete(
    "/{profile_id}", status_code=204, responses={**_ERRORS, 404: {"model": ErrorResponse}}
)
async def delete_profile(profile_id: int, request: Request, db: DbDep, user: EditorDep) -> Response:
    profile = await get_profile_or_404(db, profile_id)
    await db.delete(profile)
    await db.commit()
    log.info(
        "profile deleted",
        extra={"ip": client_ip(request), "username": user.username, "profile": profile.name},
    )
    return Response(status_code=204)


@router.post(
    "/test",
    response_model=ConnectionTestOk | ConnectionTestFail,
    responses={**_ERRORS, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def test_connection(
    body: ConnectionTestRequest, request: Request, db: DbDep, _user: EditorDep
) -> ConnectionTestOk | ConnectionTestFail:
    password = body.password
    if password is None and body.profile_id is not None:
        password = _stored_password(_box(request), await get_profile_or_404(db, body.profile_id))
    return await run_check(request, _params(body, password))


@router.post(
    "/{profile_id}/init",
    response_model=RunStarted,
    status_code=202,
    responses={
        **_ERRORS,
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def init_profile(
    profile_id: int,
    body: Annotated[InitRequest, Body()],
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    user: EditorDep,
) -> RunStarted:
    profile = await get_profile_or_404(db, profile_id)

    if body.confirm_dbname != profile.dbname:
        raise api_error(
            422, "confirm_mismatch", "Для подтверждения введите имя базы данных профиля"
        )
    if body.scale > settings.limits.max_scale:
        raise api_error(
            422,
            "scale_limit",
            f"Scale больше допустимого: максимум {settings.limits.max_scale}",
            max_scale=settings.limits.max_scale,
        )
    if (
        estimate_init_bytes(body.scale, body.fillfactor) > LARGE_INIT_BYTES
        and not body.confirm_large
    ):
        raise api_error(
            422, "large_data_unconfirmed", "Оценка объёма данных больше 50 ГБ: нужно подтверждение"
        )

    await require_ready_agent(request)
    health: HealthService = request.app.state.health
    params = profile_params(request, profile)
    check = await run_check(request, params)
    if isinstance(check, ConnectionTestFail):
        # Same structure as POST /api/profiles/test; pgbench is not started.
        raise api_error(
            422,
            check.code,
            check.message,
            **check.model_dump(exclude={"code", "message"}, mode="json"),
        )

    runs: RunManager = request.app.state.runs
    try:
        run_id = await runs.start_init(
            profile_id=profile.id,
            params=params,
            options=InitOptions(
                scale=body.scale,
                fillfactor=body.fillfactor,
                foreign_keys=body.foreign_keys,
                unlogged=body.unlogged,
            ),
            started_by=user.username,
            pgbench_version=health.pgbench_version,
            server_version=check.server_version,
        )
    except RunLimitError as exc:
        raise api_error(
            409,
            "agent_busy",
            "На агенте уже выполняется запуск. Дождитесь его завершения.",
            active_runs=runs.active_ids,
        ) from exc
    log.info(
        "init started",
        extra={
            "ip": client_ip(request),
            "username": user.username,
            "profile": profile.name,
            "run_id": run_id,
        },
    )
    return RunStarted(run_id=run_id)

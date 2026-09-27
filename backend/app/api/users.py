"""User management, admin only."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from sqlalchemy.exc import IntegrityError

from app.api.deps import AdminDep, DbDep, client_ip
from app.api.errors import api_error
from app.schemas import ErrorResponse, TemporaryPassword, UserCreate, UserOut, UserUpdate
from app.security.passwords import generate_temporary_password, hash_password
from app.security.sessions import revoke_user_sessions
from app.storage import repo
from app.storage.models import Role, User

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
}


async def _get_or_404(db: DbDep, user_id: int) -> User:
    user = await repo.get_user(db, user_id)
    if user is None:
        raise api_error(404, "user_not_found", "Пользователь не найден")
    return user


@router.get("", response_model=list[UserOut], responses=_ERRORS)
async def list_users(db: DbDep, _admin: AdminDep) -> list[User]:
    return await repo.list_users(db)


@router.post(
    "",
    response_model=TemporaryPassword,
    status_code=201,
    responses={**_ERRORS, 409: {"model": ErrorResponse}},
)
async def create_user(
    body: UserCreate, request: Request, db: DbDep, admin: AdminDep
) -> TemporaryPassword:
    password = generate_temporary_password()
    try:
        user = await repo.create_user(db, body.username, password, body.role, True)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise api_error(409, "user_exists", "Пользователь с таким логином уже есть") from exc
    log.info(
        "user created",
        extra={"ip": client_ip(request), "username": admin.username, "target": user.username},
    )
    return TemporaryPassword(user=UserOut.model_validate(user), temporary_password=password)


@router.patch(
    "/{user_id}",
    response_model=UserOut,
    responses={**_ERRORS, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def update_user(
    user_id: int, body: UserUpdate, request: Request, db: DbDep, admin: AdminDep
) -> User:
    user = await _get_or_404(db, user_id)
    new_role = body.role if body.role is not None else user.role_enum
    new_disabled = body.disabled if body.disabled is not None else user.disabled

    if user.id == admin.id and new_role != Role.admin:
        raise api_error(409, "self_demote", "Нельзя понизить собственную роль")
    if user.id == admin.id and new_disabled:
        raise api_error(409, "self_disable", "Нельзя заблокировать собственную учётную запись")

    was_active_admin = user.role_enum == Role.admin and not user.disabled
    stays_active_admin = new_role == Role.admin and not new_disabled
    if was_active_admin and not stays_active_admin and await repo.count_active_admins(db) <= 1:
        raise api_error(
            409, "last_admin", "Нельзя заблокировать или понизить последнего администратора"
        )

    user.role = new_role.value
    user.disabled = new_disabled
    if new_disabled:
        await revoke_user_sessions(db, user.id)
    await db.commit()
    log.info(
        "user updated",
        extra={
            "ip": client_ip(request),
            "username": admin.username,
            "target": user.username,
            "role": user.role,
            "disabled": user.disabled,
        },
    )
    return user


@router.post(
    "/{user_id}/reset-password",
    response_model=TemporaryPassword,
    responses={**_ERRORS, 404: {"model": ErrorResponse}},
)
async def reset_password(
    user_id: int, request: Request, db: DbDep, admin: AdminDep
) -> TemporaryPassword:
    user = await _get_or_404(db, user_id)
    password = generate_temporary_password()
    user.password_hash = hash_password(password)
    user.must_change_password = True
    user.failed_attempts = 0
    user.locked_until = None
    await revoke_user_sessions(db, user.id)
    await db.commit()
    log.info(
        "password reset",
        extra={"ip": client_ip(request), "username": admin.username, "target": user.username},
    )
    return TemporaryPassword(user=UserOut.model_validate(user), temporary_password=password)

"""Login, logout, current user and own password change."""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Request, Response

from app.api.deps import DbDep, SessionDep, SettingsDep, client_ip
from app.api.errors import api_error
from app.schemas import ErrorResponse, LoginRequest, Me, PasswordChangeRequest
from app.security.login_guard import IpLoginGuard
from app.security.passwords import hash_password, needs_rehash, verify_dummy, verify_password
from app.security.sessions import (
    SESSION_COOKIE,
    create_session,
    revoke_session,
    revoke_user_sessions,
)
from app.storage import repo
from app.storage.models import utcnow

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
}


def _locked_error(retry_after_s: int, lockout_min: int) -> Exception:
    return api_error(
        429,
        "login_locked",
        f"Слишком много неудачных попыток. Вход заблокирован на {lockout_min} мин.",
        headers={"Retry-After": str(max(retry_after_s, 1))},
        retry_after_s=max(retry_after_s, 1),
    )


@router.post("/login", response_model=Me, responses=_ERRORS)
async def login(
    body: LoginRequest, request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> Me:
    guard: IpLoginGuard = request.app.state.login_guard
    auth = settings.auth
    ip = client_ip(request)
    now = utcnow()

    ip_locked = guard.locked_until(ip, now)
    if ip_locked is not None:
        log.warning("login rejected: ip locked", extra={"ip": ip, "username": body.username})
        raise _locked_error(int((ip_locked - now).total_seconds()), auth.lockout_min)

    user = await repo.get_user_by_username(db, body.username)
    if user is not None and user.locked_until is not None and user.locked_until > now:
        log.warning("login rejected: user locked", extra={"ip": ip, "username": body.username})
        raise _locked_error(int((user.locked_until - now).total_seconds()), auth.lockout_min)

    if user is None or not verify_password(user.password_hash, body.password):
        if user is None:
            verify_dummy(body.password)
        guard.register_failure(ip, now)
        attempts_left = guard.attempts_left(ip)
        user_locked = False
        if user is not None:
            user.failed_attempts += 1
            if user.failed_attempts >= auth.max_failed_logins:
                user.failed_attempts = 0
                user.locked_until = now + timedelta(minutes=auth.lockout_min)
                user_locked = True
            attempts_left = min(attempts_left, auth.max_failed_logins - user.failed_attempts)
            await db.commit()
        log.warning("login failed", extra={"ip": ip, "username": body.username})
        if user_locked or guard.locked_until(ip, now) is not None:
            raise _locked_error(auth.lockout_min * 60, auth.lockout_min)
        raise api_error(
            401,
            "invalid_credentials",
            "Неверный логин или пароль",
            attempts_left=attempts_left,
            lockout_min=auth.lockout_min,
        )

    if user.disabled:
        log.warning("login rejected: user disabled", extra={"ip": ip, "username": user.username})
        raise api_error(403, "user_disabled", "Учётная запись заблокирована администратором")

    guard.register_success(ip)
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    user.last_login_ip = ip
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    ttl = timedelta(hours=auth.session_ttl_h)
    token, _ = await create_session(db, user, ttl, ip, now)
    await db.commit()
    log.info("login succeeded", extra={"ip": ip, "username": user.username})

    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        secure=auth.cookie_secure,
        samesite="strict",
        path="/",
    )
    return Me.model_validate(user)


@router.post("/logout", status_code=204, responses=_ERRORS)
async def logout(request: Request, response: Response, db: DbDep, session: SessionDep) -> None:
    token = request.cookies.get(SESSION_COOKIE, "")
    await revoke_session(db, token)
    await db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    log.info("logout", extra={"ip": client_ip(request), "username": session.user.username})


@router.get("/me", response_model=Me, responses=_ERRORS)
async def me(session: SessionDep) -> Me:
    return Me.model_validate(session.user)


@router.post("/password", response_model=Me, responses={**_ERRORS, 422: {"model": ErrorResponse}})
async def change_password(
    body: PasswordChangeRequest, request: Request, db: DbDep, session: SessionDep
) -> Me:
    user = session.user
    if not verify_password(user.password_hash, body.current_password):
        raise api_error(403, "wrong_password", "Текущий пароль указан неверно")
    if body.new_password == body.current_password:
        raise api_error(422, "password_reused", "Новый пароль должен отличаться от текущего")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    await revoke_user_sessions(db, user.id, except_id=session.id)
    await db.commit()
    log.info("password changed", extra={"ip": client_ip(request), "username": user.username})
    return Me.model_validate(user)

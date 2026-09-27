"""FastAPI dependencies: settings, database, current user and role checks."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error
from app.config import Settings
from app.security.sessions import SESSION_COOKIE, resolve_session, revoke_user_sessions
from app.storage.models import Role, Session, User


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as db:
        yield db


def client_ip(request: Request) -> str:
    """Real client IP: uvicorn resolves X-Forwarded-For from trusted proxies only."""
    return request.client.host if request.client else "unknown"


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


async def current_session(request: Request, db: DbDep) -> Session:
    """Any authenticated session, including one that still has to change a temporary password."""
    token = request.cookies.get(SESSION_COOKIE)
    session = await resolve_session(db, token) if token else None
    if session is None:
        await db.commit()
        raise api_error(401, "not_authenticated", "Требуется вход")
    if session.user.disabled:
        await revoke_user_sessions(db, session.user_id)
        await db.commit()
        raise api_error(401, "not_authenticated", "Учётная запись заблокирована")
    return session


SessionDep = Annotated[Session, Depends(current_session)]


async def current_user(session: SessionDep) -> User:
    if session.user.must_change_password:
        raise api_error(403, "password_change_required", "Смените временный пароль")
    return session.user


def require_role(role: Role) -> Callable[[User], Awaitable[User]]:
    async def dependency(user: Annotated[User, Depends(current_user)]) -> User:
        if not user.role_enum.allows(role):
            raise api_error(403, "forbidden", "Недостаточно прав для этого действия")
        return user

    return dependency


ViewerDep = Annotated[User, Depends(require_role(Role.viewer))]
EditorDep = Annotated[User, Depends(require_role(Role.editor))]
AdminDep = Annotated[User, Depends(require_role(Role.admin))]

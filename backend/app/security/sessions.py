"""Session tokens: issued to the browser as a cookie, stored in the database as a hash."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.storage.models import Session, User, utcnow

SESSION_COOKIE = "pgbs_session"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(
    db: AsyncSession, user: User, ttl: timedelta, ip: str | None, now: datetime | None = None
) -> tuple[str, Session]:
    token = secrets.token_urlsafe(32)
    now = now or utcnow()
    session = Session(
        token_hash=hash_token(token), user_id=user.id, expires_at=now + ttl, created_at=now, ip=ip
    )
    db.add(session)
    await db.flush()
    return token, session


async def resolve_session(
    db: AsyncSession, token: str, now: datetime | None = None
) -> Session | None:
    """Return a live session with its user, or None if the token is unknown or expired."""
    now = now or utcnow()
    result = await db.execute(
        select(Session)
        .options(joinedload(Session.user))
        .where(Session.token_hash == hash_token(token))
    )
    session = result.scalar_one_or_none()
    if session is None:
        return None
    if session.expires_at <= now:
        await db.delete(session)
        return None
    return session


async def revoke_session(db: AsyncSession, token: str) -> None:
    await db.execute(delete(Session).where(Session.token_hash == hash_token(token)))


async def revoke_user_sessions(
    db: AsyncSession, user_id: int, except_id: int | None = None
) -> None:
    stmt = delete(Session).where(Session.user_id == user_id)
    if except_id is not None:
        stmt = stmt.where(Session.id != except_id)
    await db.execute(stmt)


async def purge_expired(db: AsyncSession, now: datetime | None = None) -> None:
    await db.execute(delete(Session).where(Session.expires_at <= (now or utcnow())))

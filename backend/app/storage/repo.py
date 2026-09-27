"""Data access helpers."""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.security.passwords import hash_password
from app.storage.models import Role, User

log = logging.getLogger(__name__)


async def get_user(db: AsyncSession, user_id: int) -> User | None:
    return await db.get(User, user_id)


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.username))
    return list(result.scalars())


async def count_users(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(User)) or 0)


async def count_active_admins(db: AsyncSession) -> int:
    stmt = select(func.count()).select_from(User).where(User.role == Role.admin, ~User.disabled)
    return int(await db.scalar(stmt) or 0)


async def create_user(
    db: AsyncSession, username: str, password: str, role: Role, must_change_password: bool
) -> User:
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role.value,
        must_change_password=must_change_password,
    )
    db.add(user)
    await db.flush()
    return user


async def bootstrap_admin(db: AsyncSession, username: str | None, password: str | None) -> bool:
    """Create the first admin when the users table is empty. Returns True if created."""
    if await count_users(db) > 0:
        return False
    if not username or not password:
        log.warning(
            "no users exist and the first admin credentials are not set; "
            "set the admin env variables or run `studio users reset-admin`"
        )
        return False
    await create_user(db, username, password, Role.admin, must_change_password=False)
    await db.commit()
    log.info("first admin created", extra={"username": username})
    return True

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models.user import User


class EmailTakenError(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    return await db.scalar(select(User).where(User.email == normalize_email(email)))


async def get_user(db: AsyncSession, user_id: int) -> Optional[User]:
    return await db.get(User, user_id)


async def create_user(db: AsyncSession, email: str, full_name: str, password: str) -> User:
    email = normalize_email(email)
    if await get_user_by_email(db, email) is not None:
        raise EmailTakenError(email)
    user = User(email=email, full_name=full_name, password_hash=hash_password(password))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise EmailTakenError(email)
    await db.refresh(user)
    return user

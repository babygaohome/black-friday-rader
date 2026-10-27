from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dealradar.core.security import hash_password, verify_password
from dealradar.models import User, UserPreference


class EmailTaken(Exception):
    pass


async def register_user(session: AsyncSession, email: str, password: str, display_name: str = "") -> User:
    user = User(email=email.strip().lower(), password_hash=hash_password(password), display_name=display_name)
    user.preferences = UserPreference()
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise EmailTaken(email) from exc
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    user = (await session.execute(select(User).where(User.email == email.strip().lower()))).scalar_one_or_none()
    if user and user.status == "ACTIVE" and verify_password(password, user.password_hash):
        return user
    return None

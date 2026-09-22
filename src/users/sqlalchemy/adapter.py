from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.users.domain import User, UserCreate
from src.users.sqlalchemy import mapper
from src.users.sqlalchemy.models import UserRow


async def create(session: AsyncSession, user: UserCreate) -> User:
    row = mapper.domain_create_to_row(user)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def get_user_by_id(session: AsyncSession, user_id: UUID) -> User | None:
    result = await session.execute(select(UserRow).where(UserRow.id == user_id))
    row = result.scalar_one_or_none()

    return mapper.row_to_domain(row) if row else None


async def get_user_by_email_hash(session: AsyncSession, email_hash: str) -> User | None:
    result = await session.execute(select(UserRow).where(UserRow.email_hash == email_hash))
    row = result.scalar_one_or_none()

    return mapper.row_to_domain(row) if row else None


async def list_users(session: AsyncSession) -> Sequence[User]:
    result = await session.execute(select(UserRow))
    rows = result.scalars().all()
    return [mapper.row_to_domain(row) for row in rows]


async def delete_user(session: AsyncSession, user_id: UUID) -> bool:
    result = await session.execute(
        delete(UserRow).where(UserRow.id == user_id).returning(UserRow.id)
    )
    return result.scalar_one_or_none() is not None


from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.preferences.domain import Preference, PreferenceCreate

from . import mapper
from .models import PreferenceRow


async def create(session: AsyncSession, preference: PreferenceCreate) -> Preference:
    row = mapper.domain_create_to_row(preference)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def list_for_user(session: AsyncSession, user_id: UUID) -> Sequence[Preference]:
    result = await session.execute(
        select(PreferenceRow)
        .where(PreferenceRow.user_id == user_id)
        .order_by(PreferenceRow.created_at)
    )
    return [mapper.row_to_domain(row) for row in result.scalars().all()]


async def delete_for_user(session: AsyncSession, preference_id: UUID, user_id: UUID) -> bool:
    result = await session.execute(
        delete(PreferenceRow)
        .where(PreferenceRow.id == preference_id, PreferenceRow.user_id == user_id)
        .returning(PreferenceRow.id)
    )
    return result.scalar_one_or_none() is not None

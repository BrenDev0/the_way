from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.skills.domain import Skill, SkillCreate

from . import mapper
from .models import SkillRow


async def upsert(session: AsyncSession, skill: SkillCreate) -> Skill:
    result = await session.execute(
        select(SkillRow).where(
            SkillRow.organization_id == skill.organization_id,
            SkillRow.name == skill.name,
        )
    )
    row = result.scalar_one_or_none()

    if row is None:
        row = mapper.domain_create_to_row(skill)
        session.add(row)
    else:
        row.description = skill.description
        row.instructions = skill.instructions
        row.created_by = skill.created_by

    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def count_for_organization(session: AsyncSession, organization_id: UUID) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(SkillRow)
        .where(SkillRow.organization_id == organization_id)
    )
    return int(result.scalar_one())


async def list_for_organization(
    session: AsyncSession, organization_id: UUID
) -> Sequence[Skill]:
    result = await session.execute(
        select(SkillRow)
        .where(SkillRow.organization_id == organization_id)
        .order_by(SkillRow.name)
    )
    return [mapper.row_to_domain(row) for row in result.scalars().all()]


async def get_for_organization(
    session: AsyncSession, name: str, organization_id: UUID
) -> Skill | None:
    result = await session.execute(
        select(SkillRow).where(
            SkillRow.organization_id == organization_id,
            SkillRow.name == name,
        )
    )
    row = result.scalar_one_or_none()
    return mapper.row_to_domain(row) if row else None


async def delete_for_organization(
    session: AsyncSession, name: str, organization_id: UUID
) -> bool:
    result = await session.execute(
        delete(SkillRow)
        .where(SkillRow.organization_id == organization_id, SkillRow.name == name)
        .returning(SkillRow.id)
    )
    return result.scalar_one_or_none() is not None

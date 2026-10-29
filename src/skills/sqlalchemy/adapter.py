from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import ARRAY, Text, delete, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from src.skills.domain import Skill, SkillCreate

from . import mapper
from .models import SkillRow

# Skills are the organization's (no owner) or one person's own. `owner_id` / `user_id` below
# say whose; a person reading sees the organization's skills and their own, theirs first.


async def upsert(session: AsyncSession, skill: SkillCreate) -> Skill:
    result = await session.execute(
        select(SkillRow).where(
            SkillRow.organization_id == skill.organization_id,
            _owned_by(skill.owner_id),
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
        row.triggers = list(skill.triggers)
        if skill.files is not None:
            row.files = dict(skill.files)
        row.created_by = skill.created_by

    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


def _owned_by(owner_id: UUID | None):
    return SkillRow.owner_id.is_(None) if owner_id is None else SkillRow.owner_id == owner_id


async def count_for_organization(session: AsyncSession, organization_id: UUID) -> int:
    """The organization's own skills: the limit on them is not spent by anyone's personal ones."""
    result = await session.execute(
        select(func.count())
        .select_from(SkillRow)
        .where(SkillRow.organization_id == organization_id, SkillRow.owner_id.is_(None))
    )
    return int(result.scalar_one())


async def count_personal(session: AsyncSession, user_id: UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(SkillRow).where(SkillRow.owner_id == user_id)
    )
    return int(result.scalar_one())


async def list_for_organization(
    session: AsyncSession, organization_id: UUID, user_id: UUID | None = None
) -> Sequence[Skill]:
    """The organization's skills; with `user_id`, that person's own as well. A personal skill
    with the same name as an organization one stands in for it, for its owner only."""
    # Listed on every turn for the agent's index; the reference files stay behind. Only
    # their paths come along -- the keys, read in the database, never the text.
    file_names = literal_column(
        f"ARRAY(SELECT jsonb_object_keys({SkillRow.__tablename__}.files))", type_=ARRAY(Text)
    ).label("file_names")
    visible = SkillRow.owner_id.is_(None) if user_id is None else or_(SkillRow.owner_id.is_(None), SkillRow.owner_id == user_id)
    result = await session.execute(
        select(SkillRow, file_names)
        .options(defer(SkillRow.files))
        .where(SkillRow.organization_id == organization_id, visible)
        .order_by(SkillRow.name)
    )
    by_name: dict[str, Skill] = {}
    for row, names in result.all():
        skill = mapper.row_to_domain(row, with_files=False, file_names=list(names or []))
        if skill.name not in by_name or skill.owner_id is not None:
            by_name[skill.name] = skill
    return list(by_name.values())


async def get_for_organization(
    session: AsyncSession, name: str, organization_id: UUID, user_id: UUID | None = None
) -> Skill | None:
    """The skill by name as this person sees it: their own first, then the organization's."""
    visible = SkillRow.owner_id.is_(None) if user_id is None else or_(SkillRow.owner_id.is_(None), SkillRow.owner_id == user_id)
    result = await session.execute(
        select(SkillRow).where(SkillRow.organization_id == organization_id, SkillRow.name == name, visible)
    )
    rows = sorted(result.scalars().all(), key=lambda row: row.owner_id is None)  # personal first
    return mapper.row_to_domain(rows[0]) if rows else None


async def get_in_scope(
    session: AsyncSession, name: str, organization_id: UUID, owner_id: UUID | None
) -> Skill | None:
    """Exactly one place: the organization's skill of this name (no owner), or this person's."""
    result = await session.execute(
        select(SkillRow).where(
            SkillRow.organization_id == organization_id, SkillRow.name == name, _owned_by(owner_id)
        )
    )
    row = result.scalar_one_or_none()
    return mapper.row_to_domain(row) if row else None


async def delete_for_organization(
    session: AsyncSession, name: str, organization_id: UUID, owner_id: UUID | None = None
) -> bool:
    result = await session.execute(
        delete(SkillRow)
        .where(SkillRow.organization_id == organization_id, SkillRow.name == name, _owned_by(owner_id))
        .returning(SkillRow.id)
    )
    return result.scalar_one_or_none() is not None

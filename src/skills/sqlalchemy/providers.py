from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database.sqlalchemy import dependencies as db_dependencies
from src.skills.domain import SkillCreate
from src.skills.ports import (
    CountSkillsFn,
    DeleteSkillFn,
    GetSkillFn,
    ListSkillsForOrganizationFn,
    UpsertSkillFn,
)

from . import adapter

Session = Annotated[AsyncSession, Depends(db_dependencies.get_db_session)]


def provide_upsert_skill_fn(session: Session) -> UpsertSkillFn:
    async def upsert_skill_fn(skill: SkillCreate):
        return await adapter.upsert(session, skill)

    return upsert_skill_fn


def provide_count_skills_fn(session: Session) -> CountSkillsFn:
    async def count_skills_fn(organization_id: UUID):
        return await adapter.count_for_organization(session, organization_id)

    return count_skills_fn


def provide_list_skills_for_organization_fn(
    session: Session,
) -> ListSkillsForOrganizationFn:
    async def list_skills_for_organization_fn(organization_id: UUID):
        return await adapter.list_for_organization(session, organization_id)

    return list_skills_for_organization_fn


def provide_get_skill_fn(session: Session) -> GetSkillFn:
    async def get_skill_fn(name: str, organization_id: UUID):
        return await adapter.get_for_organization(session, name, organization_id)

    return get_skill_fn


def provide_delete_skill_fn(session: Session) -> DeleteSkillFn:
    async def delete_skill_fn(name: str, organization_id: UUID):
        return await adapter.delete_for_organization(session, name, organization_id)

    return delete_skill_fn

from typing import Annotated

from fastapi import APIRouter, Depends, status

from src.auth import dependencies as auth_dependencies
from src.users.domain import Role, User

from . import dependencies as skills_dependencies
from . import mapper
from . import use_cases as skills_use_cases
from .ports import (
    CountSkillsFn,
    DeleteSkillFn,
    GetSkillFn,
    ListSkillsForOrganizationFn,
    UpsertSkillFn,
)
from .schemas import DeleteSkillResponse, SaveSkillRequest, SkillResponse

router = APIRouter(tags=["skills"])

CurrentUser = Annotated[
    User,
    Depends(auth_dependencies.require_role(Role.OWNER, Role.ADMIN)),
]


@router.post("", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
async def save_skill_route(
    payload: SaveSkillRequest,
    current_user: CurrentUser,
    count_skills_fn: Annotated[
        CountSkillsFn,
        Depends(skills_dependencies.provide_count_skills_fn),
    ],
    get_skill_fn: Annotated[
        GetSkillFn,
        Depends(skills_dependencies.provide_get_skill_fn),
    ],
    upsert_skill_fn: Annotated[
        UpsertSkillFn,
        Depends(skills_dependencies.provide_upsert_skill_fn),
    ],
) -> SkillResponse:
    skill = await skills_use_cases.save_skill(
        organization_id=current_user.organization_id,
        name=payload.name,
        description=payload.description,
        instructions=payload.instructions,
        created_by=current_user.id,
        count_skills_fn=count_skills_fn,
        get_skill_fn=get_skill_fn,
        upsert_skill_fn=upsert_skill_fn,
    )
    return mapper.domain_to_skill_response(skill)


@router.get("", response_model=list[SkillResponse])
async def list_skills_route(
    current_user: CurrentUser,
    list_skills_for_organization_fn: Annotated[
        ListSkillsForOrganizationFn,
        Depends(skills_dependencies.provide_list_skills_for_organization_fn),
    ],
) -> list[SkillResponse]:
    skills = await skills_use_cases.list_skills(
        organization_id=current_user.organization_id,
        list_skills_for_organization_fn=list_skills_for_organization_fn,
    )
    return [mapper.domain_to_skill_response(skill) for skill in skills]


@router.get("/{name}", response_model=SkillResponse)
async def get_skill_route(
    name: str,
    current_user: CurrentUser,
    get_skill_fn: Annotated[
        GetSkillFn,
        Depends(skills_dependencies.provide_get_skill_fn),
    ],
) -> SkillResponse:
    skill = await skills_use_cases.get_skill(
        name=name,
        organization_id=current_user.organization_id,
        get_skill_fn=get_skill_fn,
    )
    return mapper.domain_to_skill_response(skill)


@router.delete("/{name}", response_model=DeleteSkillResponse)
async def delete_skill_route(
    name: str,
    current_user: CurrentUser,
    delete_skill_fn: Annotated[
        DeleteSkillFn,
        Depends(skills_dependencies.provide_delete_skill_fn),
    ],
) -> DeleteSkillResponse:
    await skills_use_cases.delete_skill(
        name=name,
        organization_id=current_user.organization_id,
        delete_skill_fn=delete_skill_fn,
    )
    return DeleteSkillResponse(detail="Skill deleted")

import re
from collections.abc import Sequence
from uuid import UUID

from src.core.exceptions import ConflictError, NotFoundError, ValidationError

from . import config, frontmatter
from .domain import Skill, SkillCreate
from .ports import (
    CountSkillsFn,
    DeleteSkillFn,
    GetSkillFn,
    ListSkillsForOrganizationFn,
    UpsertSkillFn,
)


def _not_found() -> NotFoundError:
    return NotFoundError(message="Skill not found", code="skill_not_found")


def validate_name(name: str) -> str:
    cleaned = name.strip().lower()

    if not cleaned or len(cleaned) > config.MAX_NAME_CHARS:
        raise ValidationError(
            message=f"A skill name must be 1 to {config.MAX_NAME_CHARS} characters",
            code="skill_name_invalid",
        )

    if not re.match(config.NAME_PATTERN, cleaned):
        raise ValidationError(
            message="A skill name must be kebab-case, such as 'brand-voice'",
            code="skill_name_invalid",
        )

    return cleaned


async def save_skill(
    organization_id: UUID,
    instructions: str,
    created_by: UUID,
    count_skills_fn: CountSkillsFn,
    get_skill_fn: GetSkillFn,
    upsert_skill_fn: UpsertSkillFn,
    name: str | None = None,
    description: str | None = None,
) -> Skill:
    parsed_name, parsed_description, body = frontmatter.parse(instructions)

    chosen_name = name or parsed_name
    if not chosen_name:
        raise ValidationError(
            message="A skill needs a name, either supplied or in the frontmatter",
            code="skill_name_missing",
        )

    chosen_name = validate_name(chosen_name)
    chosen_description = (description or parsed_description or "").strip()

    if len(chosen_description) > config.MAX_DESCRIPTION_CHARS:
        raise ValidationError(
            message=(
                "A skill description must be at most "
                f"{config.MAX_DESCRIPTION_CHARS} characters"
            ),
            code="skill_description_too_long",
        )

    if not body:
        raise ValidationError(
            message="A skill needs instructions",
            code="skill_instructions_missing",
        )

    if len(body) > config.MAX_INSTRUCTIONS_CHARS:
        raise ValidationError(
            message=(
                "Those instructions are longer than the "
                f"{config.MAX_INSTRUCTIONS_CHARS} character limit"
            ),
            code="skill_instructions_too_long",
        )

    existing = await get_skill_fn(chosen_name, organization_id)
    if existing is None:
        held = await count_skills_fn(organization_id)
        if held >= config.MAX_SKILLS_PER_ORGANIZATION:
            raise ConflictError(
                message=(
                    "This organization already holds the maximum of "
                    f"{config.MAX_SKILLS_PER_ORGANIZATION} skills"
                ),
                code="skill_limit_reached",
            )

    return await upsert_skill_fn(
        SkillCreate(
            organization_id=organization_id,
            name=chosen_name,
            description=chosen_description,
            instructions=body,
            created_by=created_by,
        )
    )


async def list_skills(
    organization_id: UUID,
    list_skills_for_organization_fn: ListSkillsForOrganizationFn,
) -> Sequence[Skill]:
    return await list_skills_for_organization_fn(organization_id)


async def get_skill(
    name: str,
    organization_id: UUID,
    get_skill_fn: GetSkillFn,
) -> Skill:
    skill = await get_skill_fn(name, organization_id)
    if skill is None:
        raise _not_found()
    return skill


async def delete_skill(
    name: str,
    organization_id: UUID,
    delete_skill_fn: DeleteSkillFn,
) -> None:
    if not await delete_skill_fn(name, organization_id):
        raise _not_found()

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
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


def _clean_triggers(triggers: Sequence[str]) -> list[str]:
    cleaned: list[str] = []
    for trigger in triggers:
        text = " ".join(trigger.split())
        if text and text.lower() not in {seen.lower() for seen in cleaned}:
            cleaned.append(text)

    if len(cleaned) > config.MAX_TRIGGERS:
        raise ValidationError(
            message=f"A skill can have at most {config.MAX_TRIGGERS} triggers",
            code="skill_triggers_too_many",
        )
    if any(len(trigger) > config.MAX_TRIGGER_CHARS for trigger in cleaned):
        raise ValidationError(
            message=f"Each trigger must be at most {config.MAX_TRIGGER_CHARS} characters",
            code="skill_trigger_too_long",
        )
    return cleaned


def _validate_files(files: dict[str, str]) -> dict[str, str]:
    if len(files) > config.MAX_FILES_PER_SKILL:
        raise ValidationError(
            message=f"A skill can carry at most {config.MAX_FILES_PER_SKILL} reference files",
            code="skill_files_too_many",
        )

    for path, content in files.items():
        parts = path.split("/")
        if (
            len(path) > config.MAX_FILE_PATH_CHARS
            or not re.match(config.FILE_PATH_PATTERN, path)
            or any(part in {".", ".."} for part in parts)
        ):
            raise ValidationError(
                message=f"'{path}' is not a valid reference file path",
                code="skill_file_path_invalid",
            )
        if path.lower() == "skill.md":
            raise ValidationError(
                message="SKILL.md is the skill itself, not a reference file",
                code="skill_file_path_invalid",
            )
        if len(content) > config.MAX_FILE_CHARS:
            raise ValidationError(
                message=f"'{path}' is longer than the {config.MAX_FILE_CHARS} character limit",
                code="skill_file_too_long",
            )

    if sum(len(content) for content in files.values()) > config.MAX_FILES_TOTAL_CHARS:
        raise ValidationError(
            message=(
                "A skill's reference files can hold at most "
                f"{config.MAX_FILES_TOTAL_CHARS} characters in all"
            ),
            code="skill_files_too_large",
        )
    return dict(files)


def prepare_skill(
    organization_id: UUID,
    instructions: str,
    created_by: UUID | None,
    name: str | None = None,
    description: str | None = None,
    triggers: Sequence[str] | None = None,
    files: dict[str, str] | None = None,
) -> SkillCreate:
    """Everything that makes a skill valid on its own, checked before anything is saved.
    An explicit value beats the frontmatter's, for triggers as for the name."""
    parsed = frontmatter.parse(instructions)
    body = parsed.body

    chosen_name = name or parsed.name
    if not chosen_name:
        raise ValidationError(
            message="A skill needs a name, either supplied or in the frontmatter",
            code="skill_name_missing",
        )

    chosen_name = validate_name(chosen_name)
    chosen_description = (description or parsed.description or "").strip()

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

    return SkillCreate(
        organization_id=organization_id,
        name=chosen_name,
        description=chosen_description,
        instructions=body,
        created_by=created_by,
        triggers=_clean_triggers(parsed.triggers if triggers is None else triggers),
        files=None if files is None else _validate_files(files),
    )


def _limit_reached() -> ConflictError:
    return ConflictError(
        message=(
            "This organization already holds the maximum of "
            f"{config.MAX_SKILLS_PER_ORGANIZATION} skills"
        ),
        code="skill_limit_reached",
    )


async def save_skill(
    organization_id: UUID,
    instructions: str,
    created_by: UUID,
    count_skills_fn: CountSkillsFn,
    get_skill_fn: GetSkillFn,
    upsert_skill_fn: UpsertSkillFn,
    name: str | None = None,
    description: str | None = None,
    triggers: Sequence[str] | None = None,
    files: dict[str, str] | None = None,
) -> Skill:
    skill = prepare_skill(
        organization_id=organization_id,
        instructions=instructions,
        created_by=created_by,
        name=name,
        description=description,
        triggers=triggers,
        files=files,
    )

    existing = await get_skill_fn(skill.name, organization_id)
    if existing is None:
        held = await count_skills_fn(organization_id)
        if held >= config.MAX_SKILLS_PER_ORGANIZATION:
            raise _limit_reached()

    return await upsert_skill_fn(skill)


@dataclass
class SkillImport:
    instructions: str
    files: dict[str, str] = field(default_factory=dict)


async def import_skills(
    organization_id: UUID,
    skills: Sequence[SkillImport],
    created_by: UUID,
    count_skills_fn: CountSkillsFn,
    get_skill_fn: GetSkillFn,
    upsert_skill_fn: UpsertSkillFn,
) -> list[Skill]:
    """A whole kit in one pass. Every skill is checked before any is saved, so a bad file
    leaves the organization as it was instead of half imported. A skill with the same name
    is replaced, its reference files included."""
    if not skills:
        raise ValidationError(message="There are no skills to import", code="skill_import_empty")
    if len(skills) > config.MAX_SKILLS_PER_IMPORT:
        raise ValidationError(
            message=f"One import can carry at most {config.MAX_SKILLS_PER_IMPORT} skills",
            code="skill_import_too_large",
        )

    prepared: list[SkillCreate] = []
    for position, item in enumerate(skills, start=1):
        try:
            prepared.append(
                prepare_skill(
                    organization_id=organization_id,
                    instructions=item.instructions,
                    created_by=created_by,
                    files=item.files,
                )
            )
        except ValidationError as error:
            label = frontmatter.parse(item.instructions).name or f"Skill {position}"
            raise ValidationError(message=f"{label}: {error.message}", code=error.code) from error

    names = [skill.name for skill in prepared]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise ValidationError(
            message=f"The import names the same skill twice: {', '.join(repeated)}",
            code="skill_import_duplicate",
        )

    new = 0
    for skill in prepared:
        if await get_skill_fn(skill.name, organization_id) is None:
            new += 1
    if new and await count_skills_fn(organization_id) + new > config.MAX_SKILLS_PER_ORGANIZATION:
        raise _limit_reached()

    return [await upsert_skill_fn(skill) for skill in prepared]


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

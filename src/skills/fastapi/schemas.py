from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field

from src.fastapi.schemas import ApiBaseModel

from ..domain import Skill


class SaveSkillRequest(ApiBaseModel):
    name: str | None = None
    description: str | None = None
    instructions: str
    # Omitted, triggers come from the frontmatter and files are left as they are.
    triggers: list[str] | None = None
    files: dict[str, str] | None = None


class ImportedSkill(ApiBaseModel):
    instructions: str = Field(description="The whole SKILL.md, frontmatter included")
    files: dict[str, str] = Field(
        default_factory=dict,
        description="Reference files by path relative to the skill's folder",
    )


class ImportSkillsRequest(ApiBaseModel):
    skills: list[ImportedSkill]


class SkillResponse(ApiBaseModel):
    id: UUID
    name: str
    description: str = Field(min_length=0)
    instructions: str
    triggers: list[str] = Field(default_factory=list)
    # Paths only; empty in a listing, which does not load the files.
    files: list[str] = Field(default_factory=list)
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, skill: Skill) -> Self:
        return cls(
            id=skill.id,
            name=skill.name,
            description=skill.description,
            instructions=skill.instructions,
            triggers=skill.triggers,
            files=skill.file_names or sorted(skill.files or {}),
            created_by=skill.created_by,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
        )


class DeleteSkillResponse(ApiBaseModel):
    detail: str

from datetime import datetime
from uuid import UUID

from pydantic import Field

from src.core.schemas import ApiBaseModel


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


class DeleteSkillResponse(ApiBaseModel):
    detail: str

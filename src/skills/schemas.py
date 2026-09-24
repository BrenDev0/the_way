from datetime import datetime
from uuid import UUID

from pydantic import Field

from src.core.schemas import ApiBaseModel


class SaveSkillRequest(ApiBaseModel):
    name: str | None = None
    description: str | None = None
    instructions: str


class SkillResponse(ApiBaseModel):
    id: UUID
    name: str
    description: str = Field(min_length=0)
    instructions: str
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class DeleteSkillResponse(ApiBaseModel):
    detail: str

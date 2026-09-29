from datetime import datetime
from uuid import UUID

from pydantic import Field

from src.core.schemas import ApiBaseModel

from .config import MAX_PREFERENCE_CHARS


class CreatePreferenceRequest(ApiBaseModel):
    text: str = Field(max_length=MAX_PREFERENCE_CHARS)


class PreferenceResponse(ApiBaseModel):
    id: UUID
    text: str
    created_at: datetime


class DeletePreferenceResponse(ApiBaseModel):
    detail: str

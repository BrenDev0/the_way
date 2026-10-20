from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field

from src.fastapi.schemas import ApiBaseModel

from ..config import MAX_PREFERENCE_CHARS
from ..domain import Preference


class CreatePreferenceRequest(ApiBaseModel):
    text: str = Field(max_length=MAX_PREFERENCE_CHARS)


class PreferenceResponse(ApiBaseModel):
    id: UUID
    text: str
    created_at: datetime

    @classmethod
    def from_domain(cls, preference: Preference) -> Self:
        return cls(
            id=preference.id,
            text=preference.text,
            created_at=preference.created_at,
        )


class DeletePreferenceResponse(ApiBaseModel):
    detail: str

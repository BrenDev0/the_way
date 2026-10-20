from datetime import datetime
from typing import Self
from uuid import UUID

from src.fastapi.schemas import ApiBaseModel

from ..domain import ApiKey, Provider


class IssueApiKeyRequest(ApiBaseModel):
    user_id: UUID
    provider: Provider
    secret: str
    account_id: str | None = None
    model: str | None = None


class ApiKeyResponse(ApiBaseModel):
    id: UUID
    user_id: UUID
    provider: Provider
    last_four: str
    model: str | None
    issued_by: UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, api_key: ApiKey) -> Self:
        return cls(
            id=api_key.id,
            user_id=api_key.user_id,
            provider=api_key.provider,
            last_four=api_key.last_four,
            model=api_key.model,
            issued_by=api_key.issued_by,
            created_at=api_key.created_at,
            updated_at=api_key.updated_at,
        )


class DeleteApiKeyResponse(ApiBaseModel):
    detail: str

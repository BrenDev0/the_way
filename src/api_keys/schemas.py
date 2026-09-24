from datetime import datetime
from uuid import UUID

from src.core.schemas import ApiBaseModel

from .domain import Provider


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


class DeleteApiKeyResponse(ApiBaseModel):
    detail: str

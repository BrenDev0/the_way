from datetime import datetime
from uuid import UUID

from src.core.schemas import ApiBaseModel


class UserResponse(ApiBaseModel):
    id: UUID
    organization_id: UUID
    email: str
    created_at: datetime


class DeleteUserResponse(ApiBaseModel):
    detail: str

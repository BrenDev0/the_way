from datetime import datetime
from uuid import UUID

from src.core.schemas import ApiBaseModel

from .domain import Role


class UserResponse(ApiBaseModel):
    id: UUID
    organization_id: UUID
    email: str
    role: Role
    created_at: datetime


class DeleteUserResponse(ApiBaseModel):
    detail: str

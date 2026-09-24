from datetime import datetime
from uuid import UUID

from src.core.schemas import ApiBaseModel
from src.users.domain import Role


class CreateInvitationRequest(ApiBaseModel):
    email: str
    role: Role


class InvitationResponse(ApiBaseModel):
    id: UUID
    email: str
    role: Role
    expires_at: datetime
    invited_by: UUID | None
    created_at: datetime


class AcceptInvitationRequest(ApiBaseModel):
    token: str
    password: str


class RevokeInvitationResponse(ApiBaseModel):
    detail: str

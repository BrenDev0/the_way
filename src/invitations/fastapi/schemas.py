from datetime import datetime
from typing import Self
from uuid import UUID

from src.fastapi.schemas import ApiBaseModel
from src.users.domain import Role

from ..domain import Invitation


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

    @classmethod
    def from_domain(cls, invitation: Invitation, email: str) -> Self:
        """`email` is the decrypted address; decrypting is the caller's job."""
        return cls(
            id=invitation.id,
            email=email,
            role=invitation.role,
            expires_at=invitation.expires_at,
            invited_by=invitation.invited_by,
            created_at=invitation.created_at,
        )


class AcceptInvitationRequest(ApiBaseModel):
    token: str
    password: str


class RevokeInvitationResponse(ApiBaseModel):
    detail: str

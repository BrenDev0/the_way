from datetime import UTC, datetime
from typing import Self
from uuid import UUID

from src.fastapi.schemas import ApiBaseModel
from src.staff.domain import (
    OwnerInvitation,
    OwnerInvitationStatus,
    StaffMember,
    status_of,
)


class StaffLoginRequest(ApiBaseModel):
    email: str
    password: str


class StaffResponse(ApiBaseModel):
    id: UUID
    email: str
    created_at: datetime

    @classmethod
    def from_domain(cls, staff: StaffMember, email: str) -> Self:
        """`email` is the decrypted address; decrypting is the caller's job."""
        return cls(id=staff.id, email=email, created_at=staff.created_at)


class StaffLogoutResponse(ApiBaseModel):
    detail: str


class CreateOwnerInvitationRequest(ApiBaseModel):
    organization_name: str
    email: str
    # Seats the organization may use; unset, it has no limit.
    seat_limit: int | None = None


class OwnerInvitationResponse(ApiBaseModel):
    id: UUID
    organization_name: str
    email: str
    seat_limit: int | None
    status: OwnerInvitationStatus
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    # The organization created when it was accepted.
    organization_id: UUID | None
    invited_by: UUID | None
    created_at: datetime

    @classmethod
    def from_domain(cls, invitation: OwnerInvitation, email: str) -> Self:
        """`email` is the decrypted address; decrypting is the caller's job."""
        return cls(
            id=invitation.id,
            organization_name=invitation.organization_name,
            email=email,
            seat_limit=invitation.seat_limit,
            status=status_of(invitation, datetime.now(UTC)),
            expires_at=invitation.expires_at,
            accepted_at=invitation.accepted_at,
            revoked_at=invitation.revoked_at,
            organization_id=invitation.organization_id,
            invited_by=invitation.invited_by,
            created_at=invitation.created_at,
        )


class RevokeOwnerInvitationResponse(ApiBaseModel):
    detail: str


class AcceptOwnerInvitationRequest(ApiBaseModel):
    token: str
    password: str

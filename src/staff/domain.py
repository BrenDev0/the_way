from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


@dataclass
class StaffMember:
    id: UUID
    encrypted_email: str
    email_hash: str
    password_hash: str
    created_at: datetime


@dataclass
class StaffMemberCreate:
    encrypted_email: str
    email_hash: str
    password_hash: str


@dataclass
class StaffSession:
    id: UUID
    staff_id: UUID
    token_hash: str
    expires_at: datetime
    last_seen_at: datetime
    created_at: datetime
    revoked_at: datetime | None


@dataclass
class StaffSessionCreate:
    staff_id: UUID
    token_hash: str
    expires_at: datetime
    last_seen_at: datetime


class OwnerInvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"


@dataclass
class OwnerInvitation:
    """An invitation for someone to start an organization as its owner. The organization
    does not exist yet: it is created, with the owner's account, when this is accepted."""

    id: UUID
    organization_name: str
    encrypted_email: str
    email_hash: str
    seat_limit: int | None
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    invited_by: UUID | None
    # Set when it is accepted: the organization that was created.
    organization_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass
class OwnerInvitationCreate:
    organization_name: str
    encrypted_email: str
    email_hash: str
    seat_limit: int | None
    token_hash: str
    expires_at: datetime
    invited_by: UUID | None = None


def status_of(invitation: OwnerInvitation, now: datetime) -> OwnerInvitationStatus:
    """Accepted and revoked win over expired: an invitation that was used stays 'accepted'
    after its link would have lapsed."""
    if invitation.accepted_at is not None:
        return OwnerInvitationStatus.ACCEPTED
    if invitation.revoked_at is not None:
        return OwnerInvitationStatus.REVOKED
    if invitation.expires_at <= now:
        return OwnerInvitationStatus.EXPIRED
    return OwnerInvitationStatus.PENDING

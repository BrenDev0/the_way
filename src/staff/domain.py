from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from src.invitations.domain import Invitation
from src.users.domain import Role


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
    # It was accepted and its organization has since been deleted: all that is left is the record.
    ORGANIZATION_DELETED = "organization_deleted"


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
    after its link would have lapsed -- until its organization is deleted, which clears the link
    to it (the record stays) and is what tells the two apart."""
    if invitation.accepted_at is not None:
        if invitation.organization_id is None:
            return OwnerInvitationStatus.ORGANIZATION_DELETED
        return OwnerInvitationStatus.ACCEPTED
    if invitation.revoked_at is not None:
        return OwnerInvitationStatus.REVOKED
    if invitation.expires_at <= now:
        return OwnerInvitationStatus.EXPIRED
    return OwnerInvitationStatus.PENDING


# --- every organization, as staff see them: read models across all of them ---------------


@dataclass(frozen=True)
class OrganizationSummary:
    """One organization at a glance. Counts only: staff see how big it is and whether it is
    used, never what is in it."""

    id: UUID
    name: str
    seat_limit: int | None
    created_at: datetime
    members: int
    pending_invitations: int
    owner_encrypted_email: str | None
    files: int  # files that finished uploading
    bytes: int
    last_seen_at: datetime | None  # the latest sign-in activity of anyone in it
    # whether it holds an Anthropic or OpenAI key: without one nobody in it can use the agent
    ai_enabled: bool = False


@dataclass(frozen=True)
class OrganizationMember:
    id: UUID
    encrypted_email: str
    role: Role
    created_at: datetime
    last_seen_at: datetime | None


@dataclass(frozen=True)
class OrganizationDetail:
    summary: OrganizationSummary
    members: Sequence[OrganizationMember]
    pending_invitations: Sequence[Invitation]


@dataclass(frozen=True)
class OrganizationDeletion:
    """What deleting an organization did, told to the person who did it. Nothing keeps it: the
    organization is gone, and so is every trace of it."""

    organization_name: str
    members: int
    files: int
    bytes: int
    # what clearing the bucket did: files removed, and files left behind, which is None when
    # the bucket could not be listed and so nobody can say
    files_removed: int
    files_left: int | None

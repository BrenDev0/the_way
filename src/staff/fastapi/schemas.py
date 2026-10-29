import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Self
from uuid import UUID

from pydantic import ConfigDict, Field

from src.api_keys.domain import ApiKey, Provider
from src.core.cryptography.ports import EncryptionService
from src.fastapi.schemas import ApiBaseModel
from src.invitations.fastapi.schemas import InvitationResponse
from src.staff.domain import (
    DeletedOrganization,
    OrganizationDetail,
    OrganizationMember,
    OrganizationSummary,
    OwnerInvitation,
    OwnerInvitationStatus,
    StaffMember,
    status_of,
)
from src.users.domain import Role

logger = logging.getLogger(__name__)

# What the staff panel shows for an email that cannot be decrypted.
UNREADABLE_EMAIL = "(no se pudo leer)"


def tolerant_decrypt(encryption_service: EncryptionService) -> Callable[[str], str]:
    """Decrypts for the staff panel, which exists to see every organization: one damaged record
    (an email that no longer decrypts) must show as damaged, not turn the whole list into an
    error, or the organization could be neither opened nor deleted. The failure is logged."""

    def decrypt(value: str) -> str:
        try:
            return encryption_service.decrypt(value)
        except Exception:
            logger.warning("A stored email could not be decrypted; the staff panel shows a placeholder")
            return UNREADABLE_EMAIL

    return decrypt


class StaffLoginRequest(ApiBaseModel):
    email: str
    # ApiBaseModel asks every string for 2 characters. A staff password is whatever the person
    # chose (python -m src.staff.create takes any non-empty one), so one character must sign in.
    password: str = Field(min_length=1)


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


class DeleteOwnerInvitationResponse(ApiBaseModel):
    detail: str


class AcceptOwnerInvitationRequest(ApiBaseModel):
    token: str
    password: str


class StoredDataResponse(ApiBaseModel):
    """A response built from what is stored. ApiBaseModel asks every string for two characters,
    which is a rule for what people type; a response describes what is there, and one
    organization with a one-letter name must not make the whole list fail."""

    model_config = ConfigDict(str_min_length=0)


class OrganizationSummaryResponse(StoredDataResponse):
    id: UUID
    name: str
    seat_limit: int | None
    created_at: datetime
    members: int
    pending_invitations: int
    owner_email: str | None
    files: int
    bytes: int
    last_seen_at: datetime | None
    ai_enabled: bool

    @classmethod
    def from_domain(cls, summary: OrganizationSummary, owner_email: str | None) -> Self:
        """`owner_email` is the decrypted address; decrypting is the caller's job."""
        return cls(
            id=summary.id,
            name=summary.name,
            seat_limit=summary.seat_limit,
            created_at=summary.created_at,
            members=summary.members,
            pending_invitations=summary.pending_invitations,
            owner_email=owner_email,
            files=summary.files,
            bytes=summary.bytes,
            last_seen_at=summary.last_seen_at,
            ai_enabled=summary.ai_enabled,
        )


class OrganizationMemberResponse(StoredDataResponse):
    id: UUID
    email: str
    role: Role
    created_at: datetime
    last_seen_at: datetime | None

    @classmethod
    def from_domain(cls, member: OrganizationMember, email: str) -> Self:
        return cls(
            id=member.id,
            email=email,
            role=member.role,
            created_at=member.created_at,
            last_seen_at=member.last_seen_at,
        )


class OrganizationDetailResponse(StoredDataResponse):
    organization: OrganizationSummaryResponse
    members: list[OrganizationMemberResponse]
    pending_invitations: list[InvitationResponse]

    @classmethod
    def from_domain(cls, detail: OrganizationDetail, decrypt: Callable[[str], str]) -> Self:
        """`decrypt` turns a stored email into the address; the caller provides it."""
        owner = detail.summary.owner_encrypted_email
        return cls(
            organization=OrganizationSummaryResponse.from_domain(detail.summary, decrypt(owner) if owner else None),
            members=[OrganizationMemberResponse.from_domain(m, decrypt(m.encrypted_email)) for m in detail.members],
            pending_invitations=[
                InvitationResponse.from_domain(i, email=decrypt(i.encrypted_email)) for i in detail.pending_invitations
            ],
        )


class DeleteOrganizationRequest(ApiBaseModel):
    # The organization's exact name, typed by the person deleting it. No minimum length: an
    # organization named "A" must be deletable, and a blank answer is a mismatch the use case
    # reports with its own code, not a generic validation error.
    confirmation: str = Field(min_length=0)


class DeletedOrganizationResponse(StoredDataResponse):
    id: UUID
    organization_id: UUID
    organization_name: str
    deleted_by_email: str
    members: int
    files: int
    bytes: int
    # what clearing the bucket did; files_left is null when the bucket could not be listed
    files_removed: int
    files_left: int | None
    created_at: datetime

    @classmethod
    def from_domain(cls, record: DeletedOrganization, deleted_by_email: str) -> Self:
        return cls(
            id=record.id,
            organization_id=record.organization_id,
            organization_name=record.organization_name,
            deleted_by_email=deleted_by_email,
            members=record.members,
            files=record.files,
            bytes=record.bytes,
            files_removed=record.files_removed,
            files_left=record.files_left,
            created_at=record.created_at,
        )


class SetApiKeyRequest(ApiBaseModel):
    """What staff type to set an organization key. The secret is read once and stored
    encrypted; nothing returns it."""

    secret: str
    # the CX provider location id; the other providers take none
    account_id: str | None = None
    # an LLM provider model, when it should not be the default
    model: str | None = None


class OrganizationApiKeyResponse(StoredDataResponse):
    """A key as staff see it afterwards: which provider, the last four characters, and the
    non-secret settings. Never the secret."""

    provider: Provider
    last_four: str
    model: str | None
    account_id: str | None
    set_by: UUID | None
    updated_at: datetime

    @classmethod
    def from_domain(cls, api_key: ApiKey, decrypt: Callable[[str], str]) -> Self:
        return cls(
            provider=api_key.provider,
            last_four=api_key.last_four,
            model=api_key.model,
            account_id=decrypt(api_key.encrypted_account_id) if api_key.encrypted_account_id else None,
            set_by=api_key.set_by,
            updated_at=api_key.updated_at,
        )


class DeleteOrganizationApiKeyResponse(StoredDataResponse):
    detail: str

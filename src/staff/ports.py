from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol
from uuid import UUID

from src.organizations.domain import FilesPurged

from .domain import (
    DeletedOrganization,
    DeletedOrganizationCreate,
    OrganizationMember,
    OrganizationSummary,
    OwnerInvitation,
    OwnerInvitationCreate,
    StaffMember,
    StaffMemberCreate,
    StaffSession,
    StaffSessionCreate,
)

CreateStaffMemberFn = Callable[[StaffMemberCreate], Awaitable[StaffMember]]
GetStaffMemberByIdFn = Callable[[UUID], Awaitable[StaffMember | None]]
GetStaffMemberByEmailHashFn = Callable[[str], Awaitable[StaffMember | None]]

CreateStaffSessionFn = Callable[[StaffSessionCreate], Awaitable[StaffSession]]
GetStaffSessionByTokenHashFn = Callable[[str], Awaitable[StaffSession | None]]
TouchStaffSessionFn = Callable[[UUID], Awaitable[StaffSession | None]]
RevokeStaffSessionByTokenHashFn = Callable[[str], Awaitable[bool]]

CreateOwnerInvitationFn = Callable[[OwnerInvitationCreate], Awaitable[OwnerInvitation]]
GetOwnerInvitationByTokenHashFn = Callable[[str], Awaitable[OwnerInvitation | None]]
ListOwnerInvitationsFn = Callable[[], Awaitable[Sequence[OwnerInvitation]]]
RevokeOwnerInvitationFn = Callable[[UUID], Awaitable[bool]]
GetOwnerInvitationFn = Callable[[UUID], Awaitable[OwnerInvitation | None]]
# Removes the record of an invitation for good; whether there was one to remove.
DeleteOwnerInvitationFn = Callable[[UUID], Awaitable[bool]]
RevokePendingOwnerInvitationsForEmailFn = Callable[[str], Awaitable[int]]


class ClaimOwnerInvitationFn(Protocol):
    """Mark an invitation accepted, once: False when it was already used, revoked or has
    lapsed -- so two people racing on one link cannot both get an organization."""

    async def __call__(self, invitation_id: UUID, organization_id: UUID) -> bool: ...

# Every organization, read across all of them (the staff panel), and the record kept when one is deleted.
ListOrganizationSummariesFn = Callable[[], Awaitable[Sequence[OrganizationSummary]]]
GetOrganizationSummaryFn = Callable[[UUID], Awaitable[OrganizationSummary | None]]
ListOrganizationMembersFn = Callable[[UUID], Awaitable[Sequence[OrganizationMember]]]
RecordDeletedOrganizationFn = Callable[[DeletedOrganizationCreate], Awaitable[DeletedOrganization]]
ListDeletedOrganizationsFn = Callable[[], Awaitable[Sequence[DeletedOrganization]]]
# Everything the organization has in the bucket, removed (organizations.files.purge_files).
PurgeOrganizationFilesFn = Callable[[UUID], Awaitable[FilesPurged]]

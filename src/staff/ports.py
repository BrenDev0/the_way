from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol
from uuid import UUID

from .domain import (
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
RevokePendingOwnerInvitationsForEmailFn = Callable[[str], Awaitable[int]]


class ClaimOwnerInvitationFn(Protocol):
    """Mark an invitation accepted, once: False when it was already used, revoked or has
    lapsed -- so two people racing on one link cannot both get an organization."""

    async def __call__(self, invitation_id: UUID, organization_id: UUID) -> bool: ...

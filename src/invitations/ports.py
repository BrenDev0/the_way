from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol
from uuid import UUID

from .domain import Invitation, InvitationCreate

CreateInvitationFn = Callable[[InvitationCreate], Awaitable[Invitation]]
GetInvitationByTokenHashFn = Callable[[str], Awaitable[Invitation | None]]
ListPendingForOrganizationFn = Callable[[UUID], Awaitable[Sequence[Invitation]]]
CountPendingForOrganizationFn = Callable[[UUID], Awaitable[int]]
AcceptInvitationFn = Callable[[UUID], Awaitable[Invitation | None]]


class GetPendingForEmailFn(Protocol):
    async def __call__(
        self, organization_id: UUID, email_hash: str
    ) -> Invitation | None: ...


class RevokeInvitationFn(Protocol):
    async def __call__(self, invitation_id: UUID, organization_id: UUID) -> bool: ...


class RevokePendingForEmailFn(Protocol):
    async def __call__(self, organization_id: UUID, email_hash: str) -> int: ...

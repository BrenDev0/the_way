from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import UUID

from .domain import Organization, OrganizationCreate

CreateOrganizationFn = Callable[[OrganizationCreate], Awaitable[Organization]]
GetOrganizationByIdFn = Callable[[UUID], Awaitable[Organization | None]]
DeleteOrganizationByIdFn = Callable[[UUID], Awaitable[bool]]


class UpdateOrganizationByIdFn(Protocol):
    async def __call__(
        self, organization_id: UUID, changes: dict[str, Any]
    ) -> Organization | None: ...

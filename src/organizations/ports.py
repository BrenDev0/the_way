from collections.abc import Callable, Awaitable
from uuid import UUID
from typing import Any, Protocol
from .domain import Organization, OrganizationCreate

CreateOrganizatinFn = Callable[[OrganizationCreate], Awaitable[Organization]]
GetOrganizationByIdFn = Callable[[UUID], Awaitable[Organization | None]]
DeleteOrganizationByIdFn = Callable[[UUID], Awaitable[bool]]


class UpdateOrganizationByIdFn(Protocol):
    async def __call__(self, organization_id: UUID, changes: dict[str, Any]): ...

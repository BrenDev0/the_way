from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from .domain import MonthlyUsage, Organization, OrganizationCreate, ProjectStorage

CreateOrganizationFn = Callable[[OrganizationCreate], Awaitable[Organization]]
GetOrganizationByIdFn = Callable[[UUID], Awaitable[Organization | None]]
DeleteOrganizationByIdFn = Callable[[UUID], Awaitable[bool]]

# Read-side reports over data other slices own, counted by the database rather than by
# loading every row. Every project of the organization, biggest first; and each person's
# conversations and tokens per month, from `since` on.
ListProjectStorageFn = Callable[[UUID], Awaitable[Sequence[ProjectStorage]]]
ListMonthlyUsageFn = Callable[[UUID, datetime], Awaitable[Sequence[MonthlyUsage]]]


class UpdateOrganizationByIdFn(Protocol):
    async def __call__(
        self, organization_id: UUID, changes: dict[str, Any]
    ) -> Organization | None: ...

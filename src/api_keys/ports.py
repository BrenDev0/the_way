from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol
from uuid import UUID

from .domain import ApiKey, ApiKeyCreate

UpsertApiKeyFn = Callable[[ApiKeyCreate], Awaitable[ApiKey]]
ListApiKeysForUserFn = Callable[[UUID], Awaitable[Sequence[ApiKey]]]


class ListApiKeysFn(Protocol):
    async def __call__(
        self, organization_id: UUID, user_id: UUID | None = None
    ) -> Sequence[ApiKey]: ...


class DeleteApiKeyForOrganizationFn(Protocol):
    async def __call__(self, api_key_id: UUID, organization_id: UUID) -> bool: ...

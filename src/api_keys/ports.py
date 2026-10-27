from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from .domain import ApiKey, ApiKeyCreate, Provider

UpsertApiKeyFn = Callable[[ApiKeyCreate], Awaitable[ApiKey]]
# What a user works through: the keys of the user's organization, by the user's id.
ListApiKeysForUserFn = Callable[[UUID], Awaitable[Sequence[ApiKey]]]
ListApiKeysFn = Callable[[UUID], Awaitable[Sequence[ApiKey]]]
# organization id, provider -> whether there was one to delete
DeleteApiKeyFn = Callable[[UUID, Provider], Awaitable[bool]]

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol
from uuid import UUID

from .domain import Preference, PreferenceCreate

CreatePreferenceFn = Callable[[PreferenceCreate], Awaitable[Preference]]
ListPreferencesForUserFn = Callable[[UUID], Awaitable[Sequence[Preference]]]


class DeletePreferenceForUserFn(Protocol):
    async def __call__(self, preference_id: UUID, user_id: UUID) -> bool: ...

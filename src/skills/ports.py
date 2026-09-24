from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol
from uuid import UUID

from .domain import Skill, SkillCreate

UpsertSkillFn = Callable[[SkillCreate], Awaitable[Skill]]
CountSkillsFn = Callable[[UUID], Awaitable[int]]
ListSkillsForOrganizationFn = Callable[[UUID], Awaitable[Sequence[Skill]]]


class GetSkillFn(Protocol):
    async def __call__(self, name: str, organization_id: UUID) -> Skill | None: ...


class DeleteSkillFn(Protocol):
    async def __call__(self, name: str, organization_id: UUID) -> bool: ...

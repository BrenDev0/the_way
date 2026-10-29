from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol
from uuid import UUID

from .domain import Skill, SkillCreate

UpsertSkillFn = Callable[[SkillCreate], Awaitable[Skill]]
CountSkillsFn = Callable[[UUID], Awaitable[int]]
ListSkillsForOrganizationFn = Callable[[UUID], Awaitable[Sequence[Skill]]]
# how many skills a person has of their own
CountPersonalSkillsFn = Callable[[UUID], Awaitable[int]]


class GetSkillFn(Protocol):
    async def __call__(self, name: str, organization_id: UUID) -> Skill | None: ...


class GetSkillInScopeFn(Protocol):
    """One place only: the organization's skill of this name (owner None), or this person's."""

    async def __call__(self, name: str, organization_id: UUID, owner_id: UUID | None) -> Skill | None: ...


class DeleteSkillInScopeFn(Protocol):
    async def __call__(self, name: str, organization_id: UUID, owner_id: UUID | None) -> bool: ...


class DeleteSkillFn(Protocol):
    async def __call__(self, name: str, organization_id: UUID) -> bool: ...

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.bucket.ports import BucketStore
from src.core.llm.ports import LLM


class LLMFactory(Protocol):
    """A model built from the user's own keys: the first of `preferred` whose provider
    they hold a key for, otherwise their default model."""

    async def __call__(
        self, preferred: Sequence[str] = (), temperature: float = 0.0
    ) -> LLM: ...


@dataclass(frozen=True)
class Credential:
    secret: str
    account_id: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class ToolContext:
    """Everything a slice needs to build its tools for one run, on behalf of one user.

    Tools are built fresh per run and close over this, so every call is scoped to the
    user the run belongs to -- a tool can never be pointed at someone else's data."""

    session: AsyncSession
    organization_id: UUID
    user_id: UUID
    user_role: str
    bucket_store: BucketStore
    credentials: Mapping[str, Credential]
    llm_factory: LLMFactory
    conversation_id: UUID | None = None

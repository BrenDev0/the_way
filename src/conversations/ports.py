from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol
from uuid import UUID

from src.core.llm.domain import Message

from .domain import Conversation, ConversationCreate, TurnState

CreateConversationFn = Callable[[ConversationCreate], Awaitable[Conversation]]
GetConversationByIdFn = Callable[[UUID], Awaitable[Conversation | None]]
ListMessagesFn = Callable[[UUID], Awaitable[list[Message]]]
ListConversationsForUserFn = Callable[[UUID], Awaitable[Sequence[Conversation]]]
SaveTurnStateFn = Callable[[UUID, TurnState], Awaitable[Conversation | None]]
AppendMessagesFn = Callable[[UUID, Sequence[Message]], Awaitable[int]]


class GetConversationForUserFn(Protocol):
    async def __call__(
        self, conversation_id: UUID, user_id: UUID
    ) -> Conversation | None: ...


class DeleteConversationForUserFn(Protocol):
    async def __call__(self, conversation_id: UUID, user_id: UUID) -> bool: ...


class ListMessagesForUserFn(Protocol):
    async def __call__(
        self, conversation_id: UUID, user_id: UUID
    ) -> list[Message] | None: ...

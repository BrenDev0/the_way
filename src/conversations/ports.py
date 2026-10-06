from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol
from uuid import UUID

from src.core.llm.domain import Message

from .domain import Conversation, ConversationCreate, TurnContext, TurnState

CreateConversationFn = Callable[[ConversationCreate], Awaitable[Conversation]]
GetConversationByIdFn = Callable[[UUID], Awaitable[Conversation | None]]
ListMessagesFn = Callable[[UUID], Awaitable[list[Message]]]
ListConversationsForUserFn = Callable[[UUID], Awaitable[Sequence[Conversation]]]
SaveTurnStateFn = Callable[[UUID, TurnState], Awaitable[Conversation | None]]
AppendMessagesFn = Callable[[UUID, Sequence[Message]], Awaitable[int]]
RenameConversationFn = Callable[[UUID, str], Awaitable[Conversation | None]]
# Makes what the turn has stored so far durable, mid-turn.
CommitFn = Callable[[], Awaitable[None]]
# The history as the model is sent it: attachments opened up (attachments.expand).
ExpandFn = Callable[[Sequence[Message]], Awaitable[list[Message]]]


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


# What a turn is told besides the conversation, and background-task news to relay in it.
BuildContextFn = Callable[[Conversation], Awaitable[TurnContext]]
DrainNoticesFn = Callable[[Conversation], Awaitable[str]]

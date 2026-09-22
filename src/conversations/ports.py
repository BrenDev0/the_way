from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from src.core.llm.domain import Message

from .domain import Conversation, ConversationCreate, TurnState

CreateConversationFn = Callable[[ConversationCreate], Awaitable[Conversation]]
GetConversationForUserFn = Callable[[UUID, UUID], Awaitable[Conversation | None]]
ListConversationsForUserFn = Callable[[UUID], Awaitable[Sequence[Conversation]]]
DeleteConversationForUserFn = Callable[[UUID, UUID], Awaitable[bool]]
ListMessagesForUserFn = Callable[[UUID, UUID], Awaitable[list[Message] | None]]
SaveTurnStateFn = Callable[[UUID, TurnState], Awaitable[Conversation | None]]
AppendMessagesFn = Callable[[UUID, Sequence[Message]], Awaitable[int]]

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.core.llm.domain import Message

from .domain import (
    Conversation,
    ConversationCreate,
    ConversationFolder,
    TurnContext,
    TurnState,
)

CreateConversationFn = Callable[[ConversationCreate], Awaitable[Conversation]]
GetConversationByIdFn = Callable[[UUID], Awaitable[Conversation | None]]
ListMessagesFn = Callable[[UUID], Awaitable[list[Message]]]
ListConversationsForUserFn = Callable[[UUID], Awaitable[Sequence[Conversation]]]
SaveTurnStateFn = Callable[[UUID, TurnState], Awaitable[Conversation | None]]
AppendMessagesFn = Callable[[UUID, Sequence[Message]], Awaitable[int]]
RenameConversationFn = Callable[[UUID, str], Awaitable[Conversation | None]]
# A person's folders for their chats. Every one is asked for by its owner: someone else's is not found.
ListFoldersFn = Callable[[UUID], Awaitable[Sequence[ConversationFolder]]]
CountFoldersFn = Callable[[UUID], Awaitable[int]]
# (user, name): the person's folder with that name, whatever its capitals
FindFolderByNameFn = Callable[[UUID, str], Awaitable[ConversationFolder | None]]
CreateFolderFn = Callable[[UUID, str], Awaitable[ConversationFolder]]
# (folder, user, name)
RenameFolderFn = Callable[[UUID, UUID, str], Awaitable[ConversationFolder | None]]
# (folder, user): False when there is none of theirs. Its chats go back to the main list.
DeleteFolderFn = Callable[[UUID, UUID], Awaitable[bool]]
GetFolderFn = Callable[[UUID, UUID], Awaitable[ConversationFolder | None]]
# (conversation, user, folder or None): the chat, or None when it is not theirs
MoveConversationFn = Callable[[UUID, UUID, UUID | None], Awaitable[Conversation | None]]
# Makes what the turn has stored so far durable, mid-turn.
CommitFn = Callable[[], Awaitable[None]]
# The history as the model is sent it: attachments opened up (attachments.expand).
ExpandFn = Callable[[Sequence[Message]], Awaitable[list[Message]]]
# The user's own chat messages containing any of the terms, newest first, each with when it
# was written: candidates only, up to `limit` -- ranking them is the caller's job.
SearchMessagesFn = Callable[[UUID, Sequence[str], int], Awaitable[list[tuple[Message, datetime]]]]


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

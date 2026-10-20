from collections.abc import Sequence
from uuid import UUID

from src.conversations import prompt
from src.conversations.domain import (
    Conversation,
    ConversationClient,
    ConversationCreate,
)
from src.conversations.ports import (
    CreateConversationFn,
    DeleteConversationForUserFn,
    GetConversationForUserFn,
    ListConversationsForUserFn,
    ListMessagesForUserFn,
)
from src.core.llm import domain as llm_domain
from src.core.llm.domain import Completion, Message
from src.core.llm.ports import LLM

from .common import not_found


def build_messages(message: str, history: Sequence[Message] = ()) -> list[Message]:
    return [llm_domain.system(prompt.SYSTEM), *history, llm_domain.user(message)]


async def reply(message: str, llm: LLM, history: Sequence[Message] = ()) -> Completion:
    return await llm.respond(build_messages(message, history))


async def start_conversation(
    organization_id: UUID,
    user_id: UUID,
    title: str,
    create_conversation_fn: CreateConversationFn,
    client: ConversationClient = ConversationClient.DESKTOP,
) -> Conversation:
    return await create_conversation_fn(
        ConversationCreate(
            organization_id=organization_id, user_id=user_id, title=title, client=client
        )
    )


async def get_conversation(
    conversation_id: UUID,
    user_id: UUID,
    get_conversation_for_user_fn: GetConversationForUserFn,
) -> Conversation:
    conversation = await get_conversation_for_user_fn(conversation_id, user_id)
    if conversation is None:
        raise not_found()
    return conversation


async def list_conversations(
    user_id: UUID,
    list_conversations_for_user_fn: ListConversationsForUserFn,
) -> Sequence[Conversation]:
    return await list_conversations_for_user_fn(user_id)


async def read_messages(
    conversation_id: UUID,
    user_id: UUID,
    list_messages_for_user_fn: ListMessagesForUserFn,
) -> list[Message]:
    messages = await list_messages_for_user_fn(conversation_id, user_id)
    if messages is None:
        raise not_found()
    return messages


async def delete_conversation(
    conversation_id: UUID,
    user_id: UUID,
    delete_conversation_for_user_fn: DeleteConversationForUserFn,
) -> None:
    if not await delete_conversation_for_user_fn(conversation_id, user_id):
        raise not_found()

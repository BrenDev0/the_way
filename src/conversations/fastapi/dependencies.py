from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.fastapi import dependencies as auth_dependencies
from src.conversations.domain import ConversationCreate, TurnState
from src.conversations.ports import (
    AppendMessagesFn,
    CreateConversationFn,
    DeleteConversationForUserFn,
    GetConversationByIdFn,
    GetConversationForUserFn,
    ListConversationsForUserFn,
    ListMessagesForUserFn,
    SaveTurnStateFn,
)
from src.core.bucket.ports import BucketStore
from src.core.events.ports import EventStream
from src.core.llm.domain import Message
from src.fastapi import dependencies as api_dependencies
from src.projects.files import ProjectFiles
from src.projects.sqlalchemy.store import project_files
from src.users.domain import Role, User

from ..sqlalchemy import adapter

# Who is asking: any member of an organization may use its conversations.
CurrentUser = Annotated[
    User,
    Depends(auth_dependencies.require_role(Role.OWNER, Role.ADMIN, Role.MEMBER)),
]
Events = Annotated[EventStream, Depends(api_dependencies.get_event_stream)]


def provide_create_conversation_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> CreateConversationFn:
    async def create_conversation_fn(conversation: ConversationCreate):
        return await adapter.create(session, conversation)

    return create_conversation_fn


def provide_get_conversation_for_user_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> GetConversationForUserFn:
    async def get_conversation_for_user_fn(conversation_id: UUID, user_id: UUID):
        return await adapter.get_for_user(session, conversation_id, user_id)

    return get_conversation_for_user_fn


def provide_list_conversations_for_user_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> ListConversationsForUserFn:
    async def list_conversations_for_user_fn(user_id: UUID):
        return await adapter.list_for_user(session, user_id)

    return list_conversations_for_user_fn


def provide_delete_conversation_for_user_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> DeleteConversationForUserFn:
    async def delete_conversation_for_user_fn(conversation_id: UUID, user_id: UUID):
        return await adapter.delete_for_user(session, conversation_id, user_id)

    return delete_conversation_for_user_fn


def provide_list_messages_for_user_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> ListMessagesForUserFn:
    async def list_messages_for_user_fn(conversation_id: UUID, user_id: UUID):
        return await adapter.list_messages_for_user(session, conversation_id, user_id)

    return list_messages_for_user_fn


def provide_save_turn_state_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> SaveTurnStateFn:
    async def save_turn_state_fn(conversation_id: UUID, turn: TurnState):
        return await adapter.save_turn_state(session, conversation_id, turn)

    return save_turn_state_fn


def provide_append_messages_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> AppendMessagesFn:
    async def append_messages_fn(conversation_id: UUID, messages: Sequence[Message]):
        return await adapter.append_messages(session, conversation_id, messages)

    return append_messages_fn


def provide_get_conversation_by_id_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> GetConversationByIdFn:
    async def get_conversation_by_id_fn(conversation_id: UUID):
        return await adapter.get_by_id(session, conversation_id)

    return get_conversation_by_id_fn


def provide_project_files(
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
    bucket_store: Annotated[BucketStore, Depends(api_dependencies.get_bucket_store)],
) -> ProjectFiles:
    return project_files(session, current_user.organization_id, current_user.id, bucket_store)


# The user's projects, for attaching files to a message.
Files = Annotated[ProjectFiles, Depends(provide_project_files)]

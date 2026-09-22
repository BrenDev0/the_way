from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from src.auth import dependencies as auth_dependencies
from src.users.domain import Role, User

from . import dependencies as conversations_dependencies
from . import mapper
from . import use_cases as conversations_use_cases
from .ports import (
    CreateConversationFn,
    DeleteConversationForUserFn,
    GetConversationForUserFn,
    ListConversationsForUserFn,
    ListMessagesForUserFn,
)
from .schemas import (
    ConversationResponse,
    CreateConversationRequest,
    DeleteConversationResponse,
    MessageResponse,
)

router = APIRouter(tags=["conversations"])

CurrentUser = Annotated[
    User,
    Depends(auth_dependencies.require_role(Role.OWNER, Role.ADMIN, Role.MEMBER)),
]


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def start_conversation_route(
    payload: CreateConversationRequest,
    current_user: CurrentUser,
    create_conversation_fn: Annotated[
        CreateConversationFn,
        Depends(conversations_dependencies.provide_create_conversation_fn),
    ],
) -> ConversationResponse:
    conversation = await conversations_use_cases.start_conversation(
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        title=payload.title,
        create_conversation_fn=create_conversation_fn,
    )
    return mapper.domain_to_conversation_response(conversation)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations_route(
    current_user: CurrentUser,
    list_conversations_for_user_fn: Annotated[
        ListConversationsForUserFn,
        Depends(conversations_dependencies.provide_list_conversations_for_user_fn),
    ],
) -> list[ConversationResponse]:
    conversations = await conversations_use_cases.list_conversations(
        user_id=current_user.id,
        list_conversations_for_user_fn=list_conversations_for_user_fn,
    )
    return [mapper.domain_to_conversation_response(c) for c in conversations]


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation_route(
    conversation_id: UUID,
    current_user: CurrentUser,
    get_conversation_for_user_fn: Annotated[
        GetConversationForUserFn,
        Depends(conversations_dependencies.provide_get_conversation_for_user_fn),
    ],
) -> ConversationResponse:
    conversation = await conversations_use_cases.get_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
        get_conversation_for_user_fn=get_conversation_for_user_fn,
    )
    return mapper.domain_to_conversation_response(conversation)


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages_route(
    conversation_id: UUID,
    current_user: CurrentUser,
    list_messages_for_user_fn: Annotated[
        ListMessagesForUserFn,
        Depends(conversations_dependencies.provide_list_messages_for_user_fn),
    ],
) -> list[MessageResponse]:
    messages = await conversations_use_cases.read_messages(
        conversation_id=conversation_id,
        user_id=current_user.id,
        list_messages_for_user_fn=list_messages_for_user_fn,
    )
    return [mapper.message_to_response(m) for m in messages]


@router.delete("/{conversation_id}", response_model=DeleteConversationResponse)
async def delete_conversation_route(
    conversation_id: UUID,
    current_user: CurrentUser,
    delete_conversation_for_user_fn: Annotated[
        DeleteConversationForUserFn,
        Depends(conversations_dependencies.provide_delete_conversation_for_user_fn),
    ],
) -> DeleteConversationResponse:
    await conversations_use_cases.delete_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
        delete_conversation_for_user_fn=delete_conversation_for_user_fn,
    )
    return DeleteConversationResponse(detail="Conversation deleted")

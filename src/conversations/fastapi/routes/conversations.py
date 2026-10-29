from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from src.conversations.fastapi import dependencies as conversations_dependencies
from src.conversations.fastapi.dependencies import CurrentUser
from src.conversations.fastapi.schemas import (
    ConversationResponse,
    CreateConversationRequest,
    DeleteConversationResponse,
    MessageResponse,
    MoveConversationRequest,
)
from src.conversations.ports import (
    CreateConversationFn,
    DeleteConversationForUserFn,
    GetConversationForUserFn,
    GetFolderFn,
    ListConversationsForUserFn,
    ListMessagesForUserFn,
    MoveConversationFn,
)
from src.conversations.use_cases import conversations as conversation_use_cases
from src.conversations.use_cases import folders as folder_use_cases

router = APIRouter(tags=["conversations"])


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def start_conversation_route(
    payload: CreateConversationRequest,
    current_user: CurrentUser,
    create_conversation_fn: Annotated[
        CreateConversationFn,
        Depends(conversations_dependencies.provide_create_conversation_fn),
    ],
) -> ConversationResponse:
    conversation = await conversation_use_cases.start_conversation(
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        title=payload.title,
        create_conversation_fn=create_conversation_fn,
        client=payload.client,
    )
    return ConversationResponse.from_domain(conversation)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations_route(
    current_user: CurrentUser,
    list_conversations_for_user_fn: Annotated[
        ListConversationsForUserFn,
        Depends(conversations_dependencies.provide_list_conversations_for_user_fn),
    ],
) -> list[ConversationResponse]:
    conversations = await conversation_use_cases.list_conversations(
        user_id=current_user.id,
        list_conversations_for_user_fn=list_conversations_for_user_fn,
    )
    return [ConversationResponse.from_domain(c) for c in conversations]


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation_route(
    conversation_id: UUID,
    current_user: CurrentUser,
    get_conversation_for_user_fn: Annotated[
        GetConversationForUserFn,
        Depends(conversations_dependencies.provide_get_conversation_for_user_fn),
    ],
) -> ConversationResponse:
    conversation = await conversation_use_cases.get_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
        get_conversation_for_user_fn=get_conversation_for_user_fn,
    )
    return ConversationResponse.from_domain(conversation)


@router.patch("/{conversation_id}/folder", response_model=ConversationResponse)
async def move_conversation_route(
    conversation_id: UUID,
    payload: MoveConversationRequest,
    current_user: CurrentUser,
    get_folder_fn: Annotated[GetFolderFn, Depends(conversations_dependencies.provide_get_folder_fn)],
    move_conversation_fn: Annotated[
        MoveConversationFn, Depends(conversations_dependencies.provide_move_conversation_fn)
    ],
) -> ConversationResponse:
    """Files the chat in one of the person's folders; a null folderId takes it out of its folder."""
    conversation = await folder_use_cases.move_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
        folder_id=payload.folder_id,
        get_folder_fn=get_folder_fn,
        move_conversation_fn=move_conversation_fn,
    )
    return ConversationResponse.from_domain(conversation)


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages_route(
    conversation_id: UUID,
    current_user: CurrentUser,
    list_messages_for_user_fn: Annotated[
        ListMessagesForUserFn,
        Depends(conversations_dependencies.provide_list_messages_for_user_fn),
    ],
) -> list[MessageResponse]:
    messages = await conversation_use_cases.read_messages(
        conversation_id=conversation_id,
        user_id=current_user.id,
        list_messages_for_user_fn=list_messages_for_user_fn,
    )
    return [MessageResponse.from_domain(m) for m in messages]


@router.delete("/{conversation_id}", response_model=DeleteConversationResponse)
async def delete_conversation_route(
    conversation_id: UUID,
    current_user: CurrentUser,
    delete_conversation_for_user_fn: Annotated[
        DeleteConversationForUserFn,
        Depends(conversations_dependencies.provide_delete_conversation_for_user_fn),
    ],
) -> DeleteConversationResponse:
    await conversation_use_cases.delete_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
        delete_conversation_for_user_fn=delete_conversation_for_user_fn,
    )
    return DeleteConversationResponse(detail="Conversation deleted")

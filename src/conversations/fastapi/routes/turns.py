from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from src.api_keys import use_cases as api_keys_use_cases
from src.api_keys.fastapi import dependencies as api_keys_dependencies
from src.api_keys.ports import ListApiKeysForUserFn
from src.conversations import events as conversation_events
from src.conversations.attachments import attachment_blocks
from src.conversations.fastapi import dependencies as conversations_dependencies
from src.conversations.fastapi.dependencies import CurrentUser, Events, Files
from src.conversations.fastapi.schemas import (
    ConversationResponse,
    ResolveToolCallsRequest,
    ResumeTurnRequest,
    SendMessageRequest,
)
from src.conversations.ports import (
    AppendMessagesFn,
    GetConversationForUserFn,
    SaveTurnStateFn,
)
from src.conversations.tasks import advance_conversation
from src.conversations.use_cases import turns as turn_use_cases

router = APIRouter(tags=["conversations"])


@router.post(
    "/{conversation_id}/messages",
    response_model=ConversationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_message_route(
    conversation_id: UUID,
    payload: SendMessageRequest,
    current_user: CurrentUser,
    get_conversation_for_user_fn: Annotated[
        GetConversationForUserFn,
        Depends(conversations_dependencies.provide_get_conversation_for_user_fn),
    ],
    append_messages_fn: Annotated[
        AppendMessagesFn,
        Depends(conversations_dependencies.provide_append_messages_fn),
    ],
    save_turn_state_fn: Annotated[
        SaveTurnStateFn,
        Depends(conversations_dependencies.provide_save_turn_state_fn),
    ],
    list_api_keys_for_user_fn: Annotated[
        ListApiKeysForUserFn,
        Depends(api_keys_dependencies.provide_list_api_keys_for_user_fn),
    ],
    event_stream: Events,
    files: Files,
) -> ConversationResponse:
    await api_keys_use_cases.resolve_llm_credential(
        user_id=current_user.id,
        list_api_keys_for_user_fn=list_api_keys_for_user_fn,
    )

    conversation = await turn_use_cases.send_message(
        conversation_id=conversation_id,
        user_id=current_user.id,
        message=payload.message,
        get_conversation_for_user_fn=get_conversation_for_user_fn,
        append_messages_fn=append_messages_fn,
        save_turn_state_fn=save_turn_state_fn,
        attachments=await attachment_blocks(payload.attachments, files.owned_file),
    )

    await conversation_events.ConversationEvents(event_stream, conversation.id).status(conversation)
    await advance_conversation.kiq(conversation.id, voice=payload.voice, local_folder=payload.local_folder, remote_folder=payload.remote_folder)  # type: ignore[call-overload]

    return ConversationResponse.from_domain(conversation)


@router.post(
    "/{conversation_id}/tool-results",
    response_model=ConversationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resolve_tool_calls_route(
    conversation_id: UUID,
    payload: ResolveToolCallsRequest,
    current_user: CurrentUser,
    get_conversation_for_user_fn: Annotated[
        GetConversationForUserFn,
        Depends(conversations_dependencies.provide_get_conversation_for_user_fn),
    ],
    save_turn_state_fn: Annotated[
        SaveTurnStateFn,
        Depends(conversations_dependencies.provide_save_turn_state_fn),
    ],
    event_stream: Events,
) -> ConversationResponse:
    conversation = await turn_use_cases.resolve_tool_calls(
        conversation_id=conversation_id,
        user_id=current_user.id,
        resolutions=[r.to_domain() for r in payload.resolutions],
        get_conversation_for_user_fn=get_conversation_for_user_fn,
        save_turn_state_fn=save_turn_state_fn,
    )

    await conversation_events.ConversationEvents(event_stream, conversation.id).status(conversation)
    await advance_conversation.kiq(conversation.id, voice=payload.voice, local_folder=payload.local_folder, remote_folder=payload.remote_folder)  # type: ignore[call-overload]

    return ConversationResponse.from_domain(conversation)


@router.post(
    "/{conversation_id}/resume",
    response_model=ConversationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_turn_route(
    conversation_id: UUID,
    payload: ResumeTurnRequest,
    current_user: CurrentUser,
    get_conversation_for_user_fn: Annotated[
        GetConversationForUserFn,
        Depends(conversations_dependencies.provide_get_conversation_for_user_fn),
    ],
    save_turn_state_fn: Annotated[
        SaveTurnStateFn,
        Depends(conversations_dependencies.provide_save_turn_state_fn),
    ],
    event_stream: Events,
) -> ConversationResponse:
    """Carries on a paused turn from where it stopped. 409 conversation_not_paused when
    there is nothing paused to resume."""
    conversation = await turn_use_cases.resume_turn(
        conversation_id=conversation_id,
        user_id=current_user.id,
        get_conversation_for_user_fn=get_conversation_for_user_fn,
        save_turn_state_fn=save_turn_state_fn,
    )

    await conversation_events.ConversationEvents(event_stream, conversation.id).status(conversation)
    await advance_conversation.kiq(conversation.id, voice=payload.voice, local_folder=payload.local_folder, remote_folder=payload.remote_folder)  # type: ignore[call-overload]

    return ConversationResponse.from_domain(conversation)

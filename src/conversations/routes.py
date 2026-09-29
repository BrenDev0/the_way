from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api import dependencies as api_dependencies
from src.api_keys import dependencies as api_keys_dependencies
from src.api_keys import use_cases as api_keys_use_cases
from src.api_keys.ports import ListApiKeysForUserFn
from src.auth import dependencies as auth_dependencies
from src.core.database.sqlalchemy import dependencies as db_dependencies
from src.core.events import sse
from src.core.events.domain import EventStreamUnavailable
from src.core.events.ports import EventStream
from src.core.exceptions import ServiceUnavailableError
from src.users.domain import Role, User

from . import config, mapper
from . import dependencies as conversations_dependencies
from . import events as conversation_events
from . import use_cases as conversations_use_cases
from .ports import (
    AppendMessagesFn,
    CreateConversationFn,
    DeleteConversationForUserFn,
    GetConversationForUserFn,
    ListConversationsForUserFn,
    ListMessagesForUserFn,
    SaveTurnStateFn,
)
from .schemas import (
    ConversationResponse,
    CreateConversationRequest,
    DeleteConversationResponse,
    MessageResponse,
    ResolveToolCallsRequest,
    SendMessageRequest,
)
from .tasks import advance_conversation

router = APIRouter(tags=["conversations"])

CurrentUser = Annotated[
    User,
    Depends(auth_dependencies.require_role(Role.OWNER, Role.ADMIN, Role.MEMBER)),
]
Events = Annotated[EventStream, Depends(api_dependencies.get_event_stream)]


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
        client=payload.client,
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
) -> ConversationResponse:
    await api_keys_use_cases.resolve_llm_credential(
        user_id=current_user.id,
        list_api_keys_for_user_fn=list_api_keys_for_user_fn,
    )

    conversation = await conversations_use_cases.send_message(
        conversation_id=conversation_id,
        user_id=current_user.id,
        message=payload.message,
        get_conversation_for_user_fn=get_conversation_for_user_fn,
        append_messages_fn=append_messages_fn,
        save_turn_state_fn=save_turn_state_fn,
    )

    await conversation_events.ConversationEvents(event_stream, conversation.id).status(conversation)
    await advance_conversation.kiq(conversation.id)  # type: ignore[call-overload]

    return mapper.domain_to_conversation_response(conversation)


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
    conversation = await conversations_use_cases.resolve_tool_calls(
        conversation_id=conversation_id,
        user_id=current_user.id,
        resolutions=[mapper.resolution_request_to_domain(r) for r in payload.resolutions],
        get_conversation_for_user_fn=get_conversation_for_user_fn,
        save_turn_state_fn=save_turn_state_fn,
    )

    await conversation_events.ConversationEvents(event_stream, conversation.id).status(conversation)
    await advance_conversation.kiq(conversation.id)  # type: ignore[call-overload]

    return mapper.domain_to_conversation_response(conversation)


@router.get("/{conversation_id}/events")
async def conversation_events_route(
    conversation_id: UUID,
    request: Request,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(db_dependencies.get_db_session)],
    get_conversation_for_user_fn: Annotated[
        GetConversationForUserFn,
        Depends(conversations_dependencies.provide_get_conversation_for_user_fn),
    ],
    event_stream: Events,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """The conversation as it happens, as server-sent events: its current state first, then
    status changes, reply text as it is written, messages and tool activity, with a
    keep-alive comment after 15 quiet seconds. Reconnect with Last-Event-ID to carry on
    from the last event received."""
    # Where to read from is fixed before the state is read, so nothing falls between them.
    try:
        after = conversation_events.resume_point(last_event_id) or await event_stream.last_id(
            conversation_events.topic(conversation_id)
        )
    except EventStreamUnavailable as exc:
        raise ServiceUnavailableError("Conversation events are unavailable, try again", "events_unavailable") from exc
    conversation = await conversations_use_cases.get_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
        get_conversation_for_user_fn=get_conversation_for_user_fn,
    )
    # A stream can stay open for hours; it must not hold a database connection meanwhile.
    await session.commit()

    snapshot = mapper.domain_to_conversation_response(conversation).model_dump(mode="json", by_alias=True)
    return StreamingResponse(
        conversation_events.follow(
            event_stream,
            conversation.id,
            after,
            snapshot,
            request.is_disconnected,
            config.KEEP_ALIVE_SECONDS,
            config.STREAM_MAX_SECONDS,
        ),
        media_type="text/event-stream",
        headers=sse.HEADERS,
    )

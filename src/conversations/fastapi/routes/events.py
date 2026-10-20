from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.conversations import config
from src.conversations import events as conversation_events
from src.conversations.fastapi import dependencies as conversations_dependencies
from src.conversations.fastapi.dependencies import CurrentUser, Events
from src.conversations.fastapi.schemas import (
    ConversationResponse,
)
from src.conversations.ports import (
    GetConversationForUserFn,
)
from src.conversations.use_cases import conversations as conversation_use_cases
from src.core.events import sse
from src.core.events.domain import EventStreamUnavailable
from src.core.exceptions import ServiceUnavailableError
from src.fastapi import dependencies as api_dependencies

router = APIRouter(tags=["conversations"])


@router.get("/{conversation_id}/events")
async def conversation_events_route(
    conversation_id: UUID,
    request: Request,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
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
    conversation = await conversation_use_cases.get_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
        get_conversation_for_user_fn=get_conversation_for_user_fn,
    )
    # A stream can stay open for hours; it must not hold a database connection meanwhile.
    await session.commit()

    snapshot = ConversationResponse.from_domain(conversation).model_dump(mode="json", by_alias=True)
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

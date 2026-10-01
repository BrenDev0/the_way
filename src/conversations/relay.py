"""The agent speaking up on its own when a background task ends.

A task that finishes is reported in the conversation that started it -- right away if the
conversation is idle, by a turn the server opens itself; if a turn is under way (or waits on
the user), as soon as that turn ends. Either way the reply is the ordinary one: the turn
drains the task's notice and the assistant tells the user what was produced.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.background.sqlalchemy import adapter as background_adapter
from src.core.events.ports import EventStream

from .events import ConversationEvents
from .sqlalchemy import adapter


async def has_news(session: AsyncSession, conversation_id: UUID) -> bool:
    return bool(await background_adapter.list_unreported(session, conversation_id))


async def start(session: AsyncSession, conversation_id: UUID, event_stream: EventStream | None) -> bool:
    """Opens a reporting turn if the conversation is idle and something waits to be told.
    False, and nothing changes, if it is busy -- the busy turn's end tries again."""
    if not await has_news(session, conversation_id):
        return False
    claimed = await adapter.claim_if_idle(session, conversation_id)
    if claimed is None:
        return False
    # committed before anyone is told: a watcher that sees "running" must find it running
    await session.commit()
    if event_stream is not None:
        await ConversationEvents(event_stream, conversation_id).status(claimed)

    from .tasks import advance_conversation  # the worker module imports every tool

    await advance_conversation.kiq(conversation_id)  # type: ignore[call-overload]
    return True

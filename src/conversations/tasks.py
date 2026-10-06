import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import Context, TaskiqDepends

from src.api_keys import credentials as api_keys_credentials
from src.api_keys.sqlalchemy import adapter as api_keys_adapter
from src.assistants import catalog
from src.background import tools as background_tools
from src.core.bucket.ports import BucketStore
from src.core.bucket.unavailable import UnavailableBucketStore
from src.core.cryptography.ports import EncryptionService
from src.core.database.sqlalchemy.core import async_session_factory
from src.core.events.ports import EventStream
from src.core.llm.domain import LLMUnavailable, Message
from src.core.llm.ports import LLM
from src.core.tasks.broker import broker
from src.core.tools.context import LLMFactory, ToolContext
from src.core.tools.executor import Executor
from src.core.tools.gates import SuspendGate
from src.crm import tools as crm_tools
from src.crm.prompt import WORKFLOW
from src.knowledge import tools as knowledge_tools
from src.preferences import tools as preference_tools
from src.projects.files import ProjectFiles
from src.users.sqlalchemy import adapter as users_adapter
from src.worker import dependencies as worker_dependencies

from . import attachments, config, prompt, relay
from . import tools as conversation_tools
from . import use_cases as conversations_use_cases
from .domain import (
    Conversation,
    ConversationClient,
    ConversationStatus,
    PauseReason,
    TurnContext,
    TurnPause,
    TurnState,
)
from .events import ConversationEvents
from .sqlalchemy import adapter

READY_ATTEMPTS = 40
READY_INTERVAL_SECONDS = 0.1


async def wait_until_running(session: AsyncSession, conversation_id: UUID, run: str | None = None) -> bool:
    """Whether there is a running turn for this run to work on -- polled a moment, since
    the message can arrive before the request that sent it has committed. With `run`, the
    turn is also claimed for it, and committed, so no second run takes it."""
    for attempt in range(READY_ATTEMPTS):
        if run is not None:
            if await adapter.claim_turn(session, conversation_id, run):
                await session.commit()
                return True
        else:
            conversation = await adapter.get_by_id(session, conversation_id)
            if conversation and conversation.turn.status is ConversationStatus.RUNNING:
                return True
        if attempt + 1 == READY_ATTEMPTS:
            return False
        await session.rollback()
        await asyncio.sleep(READY_INTERVAL_SECONDS)
    return False


@broker.task
async def advance_conversation(
    conversation_id: UUID,
    encryption_service: Annotated[
        EncryptionService,
        TaskiqDepends(worker_dependencies.get_encryption_service),
    ],
    bucket_store: Annotated[
        BucketStore,
        TaskiqDepends(worker_dependencies.get_bucket_store),
    ],
    event_stream: Annotated[
        EventStream,
        TaskiqDepends(worker_dependencies.get_event_stream),
    ],
    context: Annotated[Context, TaskiqDepends()],
    voice: bool = False,
    local_folder: str | None = None,
    remote_folder: str | None = None,
) -> str | None:
    return await run_turn(
        conversation_id,
        encryption_service=encryption_service,
        bucket_store=bucket_store,
        event_stream=event_stream,
        voice=voice,
        local_folder=local_folder,
        remote_folder=remote_folder,
        run=context.message.task_id,
    )


async def _credentials(
    session: AsyncSession, user_id: UUID, encryption_service: EncryptionService | None
) -> dict:
    if encryption_service is None:
        return {}

    async def list_api_keys_for_user_fn(uid: UUID):
        return await api_keys_adapter.list_for_user(session, uid)

    return await api_keys_credentials.load_credentials(
        user_id, list_api_keys_for_user_fn, encryption_service
    )


async def run_turn(
    conversation_id: UUID,
    encryption_service: EncryptionService | None = None,
    llm: LLM | None = None,
    bucket_store: BucketStore | None = None,
    llm_factory: LLMFactory | None = None,
    event_stream: EventStream | None = None,
    voice: bool = False,
    local_folder: str | None = None,
    remote_folder: str | None = None,
    run: str | None = None,
) -> str | None:
    events = ConversationEvents(event_stream, conversation_id) if event_stream else None
    async with async_session_factory() as session:
        try:
            if not await wait_until_running(session, conversation_id, run):
                return None

            conversation = await adapter.get_by_id(session, conversation_id)
            if conversation is None:
                return None

            if llm is None and encryption_service is None:
                raise ValueError("run_turn needs an encryption service or an llm")

            credentials = await _credentials(session, conversation.user_id, encryption_service)
            factory = llm_factory or api_keys_credentials.build_llm_factory(credentials)
            if llm is None:
                llm = await factory()

            user = await users_adapter.get_user_by_id(session, conversation.user_id)
            context = ToolContext(
                session=session,
                organization_id=conversation.organization_id,
                user_id=conversation.user_id,
                user_role=str(user.role) if user else "",
                bucket_store=bucket_store or UnavailableBucketStore(),
                credentials=credentials,
                llm_factory=factory,
                conversation_id=conversation.id,
                events=events,
            )
            desktop = conversation.client is ConversationClient.DESKTOP

            async def build_context_fn(current: Conversation) -> TurnContext:
                return await turn_context(context, desktop, voice, local_folder, remote_folder)

            async def drain_notices_fn(current: Conversation) -> str:
                return await background_tools.drain_notices(context)

            async def get_conversation_by_id_fn(cid: UUID):
                return await adapter.get_by_id(session, cid)

            async def list_messages_fn(cid: UUID):
                return await adapter.list_messages(session, cid)

            async def append_messages_fn(cid: UUID, messages: Sequence[Message]):
                return await adapter.append_messages(session, cid, messages)

            files = ProjectFiles(session, conversation.organization_id, conversation.user_id, context.bucket_store)

            async def expand_fn(history: Sequence[Message]) -> list[Message]:
                return await attachments.expand(history, files.bytes_of)

            saved: list[Conversation] = []

            async def save_turn_state_fn(cid: UUID, turn: TurnState):
                updated = await adapter.save_turn_state(session, cid, turn)
                if updated is not None:
                    saved.append(updated)
                return updated

            status = await conversations_use_cases.advance_turn(
                conversation_id=conversation_id,
                llm=llm,
                executor=Executor(conversation_tools.build(context, desktop), SuspendGate(), events),
                get_conversation_by_id_fn=get_conversation_by_id_fn,
                list_messages_fn=list_messages_fn,
                append_messages_fn=append_messages_fn,
                save_turn_state_fn=save_turn_state_fn,
                build_context_fn=build_context_fn,
                drain_notices_fn=drain_notices_fn,
                observer=events,
                commit_fn=session.commit,
                expand_fn=expand_fn,
            )
            await session.commit()
            # Named before the turn is announced over: a client stops listening at idle, so
            # the title has to ride on that last status to reach it.
            if status is ConversationStatus.IDLE and (named := await _name(session, conversation_id, factory)):
                saved.append(named)
            # A task that ended while this turn ran is reported now, straight on: the turn
            # it opens says "running", so a watcher carries on into the report.
            if status is ConversationStatus.IDLE and await relay.start(session, conversation_id, event_stream):
                return status
            # Only once committed: a client that sees "awaiting_client" answers at once, and
            # the answer must find the pause already in the database.
            if events and saved:
                await events.status(saved[-1])
            return status
        except LLMUnavailable as exc:
            # The loop pauses on the model being unreachable; this is the rare call outside
            # it (building the model, say). Same outcome: kept, paused, retryable.
            await session.rollback()
            pause = conversations_use_cases.paused(PauseReason(exc.reason), exc.detail, exc.retry_after)
            await _announce(events, await _mark_paused(conversation_id, pause))
            return ConversationStatus.PAUSED
        except asyncio.CancelledError:
            # The worker is going down mid-turn. What the turn did up to its last checkpoint
            # is committed; it is paused, not failed, so the user can carry on from there.
            await session.rollback()
            pause = conversations_use_cases.paused(PauseReason.INTERRUPTED)
            await asyncio.shield(_pause_and_announce(conversation_id, pause, events))
            raise
        except Exception:
            await session.rollback()
            failed = await _mark_failed(conversation_id)
            if events and failed:
                await events.status(failed)
            raise


async def turn_context(
    context: ToolContext,
    desktop: bool,
    voice: bool = False,
    local_folder: str | None = None,
    remote_folder: str | None = None,
) -> TurnContext:
    """Most stable first: the CX workflow changes only when a key is issued and the
    knowledge index when a document or skill does -- those go ahead of the history. The
    rest can change any message, and goes after it."""
    stable = []
    if crm_tools.available(context):
        stable.append(WORKFLOW)
    stable.append(await knowledge_tools.build_context(context.session, context.organization_id))

    now = datetime.now(UTC)
    current = prompt.turn_context(
        date_line=f"{now:%A, %Y-%m-%d} UTC",
        preferences=await preference_tools.context_block(context),
        unavailable=catalog.unavailable(context),
        desktop=desktop,
        voice=voice,
        local_folder=local_folder,
        remote_folder=remote_folder,
    )
    return TurnContext(stable=tuple(stable), current=current)


async def _name(session: AsyncSession, conversation_id: UUID, factory: LLMFactory) -> Conversation | None:
    """Names the conversation after its first exchange, with a cheap model. Best effort: a
    placeholder title is no reason to fail a turn that has already succeeded."""
    try:
        conversation = await adapter.get_by_id(session, conversation_id)
        if conversation is None:
            return None
        history = await adapter.list_messages(session, conversation_id)
        # checked before a model is built: most turns are in a conversation already named
        if not conversations_use_cases.unnamed(conversation.title, history):
            return None

        async def rename_fn(cid: UUID, title: str) -> Conversation | None:
            return await adapter.rename(session, cid, title)

        named = await conversations_use_cases.name_conversation(
            conversation,
            history,
            await factory(config.TITLE_MODELS, config.TITLE_TEMPERATURE),
            rename_fn,
        )
        await session.commit()
        return named
    except Exception:  # noqa: BLE001
        await session.rollback()
        return None


async def _mark_paused(conversation_id: UUID, pause: TurnPause) -> Conversation | None:
    """Pauses the turn as it stands in the database -- its last checkpoint -- with
    nothing pending: whatever ran after that checkpoint is redone on resume."""
    async with async_session_factory() as session:
        current = await adapter.get_by_id(session, conversation_id)
        if current is None or current.turn.status is not ConversationStatus.RUNNING:
            return current
        turn = current.turn
        paused_turn = TurnState(
            status=ConversationStatus.PAUSED,
            pending_tool_calls=turn.pending_tool_calls,
            completed_tool_results=turn.completed_tool_results,
            iterations_used=turn.iterations_used,
            usage=turn.usage,
            pending_requests=turn.pending_requests,
            decisions=turn.decisions,
            pause=pause,
        )
        result = await adapter.save_turn_state(session, conversation_id, paused_turn)
        await session.commit()
        return result


async def _announce(events: ConversationEvents | None, conversation: Conversation | None) -> None:
    if events and conversation:
        await events.status(conversation)


async def _pause_and_announce(
    conversation_id: UUID, pause: TurnPause, events: ConversationEvents | None
) -> None:
    await _announce(events, await _mark_paused(conversation_id, pause))


async def _mark_failed(conversation_id: UUID) -> Conversation | None:
    async with async_session_factory() as session:
        failed = await adapter.save_turn_state(
            session, conversation_id, TurnState(status=ConversationStatus.FAILED)
        )
        await session.commit()
        return failed

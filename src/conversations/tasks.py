import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import TaskiqDepends

from src.api_keys import credentials as api_keys_credentials
from src.api_keys.sqlalchemy import adapter as api_keys_adapter
from src.assistants import catalog
from src.background import tools as background_tools
from src.core.bucket.ports import BucketStore
from src.core.bucket.unavailable import UnavailableBucketStore
from src.core.cryptography.ports import EncryptionService
from src.core.database.sqlalchemy.core import async_session_factory
from src.core.events.ports import EventStream
from src.core.llm.domain import Message
from src.core.llm.ports import LLM
from src.core.tasks.broker import broker
from src.core.tools.context import LLMFactory, ToolContext
from src.core.tools.executor import Executor
from src.core.tools.gates import SuspendGate
from src.crm import tools as crm_tools
from src.crm.prompt import WORKFLOW
from src.knowledge import tools as knowledge_tools
from src.preferences import tools as preference_tools
from src.users.sqlalchemy import adapter as users_adapter
from src.worker import dependencies as worker_dependencies

from . import prompt
from . import tools as conversation_tools
from . import use_cases as conversations_use_cases
from .domain import Conversation, ConversationClient, ConversationStatus, TurnState
from .events import ConversationEvents
from .sqlalchemy import adapter

READY_ATTEMPTS = 40
READY_INTERVAL_SECONDS = 0.1


async def wait_until_running(session: AsyncSession, conversation_id: UUID) -> bool:
    for attempt in range(READY_ATTEMPTS):
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
) -> str | None:
    return await run_turn(
        conversation_id,
        encryption_service=encryption_service,
        bucket_store=bucket_store,
        event_stream=event_stream,
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
) -> str | None:
    events = ConversationEvents(event_stream, conversation_id) if event_stream else None
    async with async_session_factory() as session:
        try:
            if not await wait_until_running(session, conversation_id):
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

            async def build_context_fn(current: Conversation) -> Sequence[str]:
                return await turn_context(context, desktop)

            async def drain_notices_fn(current: Conversation) -> str:
                return await background_tools.drain_notices(context)

            async def get_conversation_by_id_fn(cid: UUID):
                return await adapter.get_by_id(session, cid)

            async def list_messages_fn(cid: UUID):
                return await adapter.list_messages(session, cid)

            async def append_messages_fn(cid: UUID, messages: Sequence[Message]):
                return await adapter.append_messages(session, cid, messages)

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
            )
            await session.commit()
            # Only once committed: a client that sees "awaiting_client" answers at once, and
            # the answer must find the pause already in the database.
            if events and saved:
                await events.status(saved[-1])
            return status
        except Exception:
            await session.rollback()
            failed = await _mark_failed(conversation_id)
            if events and failed:
                await events.status(failed)
            raise


async def turn_context(context: ToolContext, desktop: bool) -> list[str]:
    """The system blocks after the prompt, most stable first: the CX workflow changes only
    when a key is issued, the knowledge index when a document or skill does, and the
    per-turn block every day."""
    blocks = []
    if crm_tools.available(context):
        blocks.append(WORKFLOW)

    blocks.append(await knowledge_tools.build_context(context.session, context.organization_id))

    now = datetime.now(UTC)
    blocks.append(
        prompt.turn_context(
            date_line=f"{now:%A, %Y-%m-%d} UTC",
            preferences=await preference_tools.context_block(context),
            unavailable=catalog.unavailable(context),
            desktop=desktop,
        )
    )
    return blocks


async def _mark_failed(conversation_id: UUID) -> Conversation | None:
    async with async_session_factory() as session:
        failed = await adapter.save_turn_state(
            session, conversation_id, TurnState(status=ConversationStatus.FAILED)
        )
        await session.commit()
        return failed

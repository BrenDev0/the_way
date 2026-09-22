import asyncio
from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import TaskiqDepends

from src.core.database.sqlalchemy.core import async_session_factory
from src.core.llm.domain import Message
from src.core.llm.ports import LLM
from src.core.tasks.broker import broker
from src.core.tools.executor import Executor
from src.core.tools.gates import DenyGate
from src.worker import dependencies as worker_dependencies

from . import use_cases as conversations_use_cases
from .domain import ConversationStatus, TurnState
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
    llm: Annotated[LLM, TaskiqDepends(worker_dependencies.get_llm)],
) -> str | None:
    return await run_turn(conversation_id, llm)


async def run_turn(conversation_id: UUID, llm: LLM) -> str | None:
    async with async_session_factory() as session:
        try:
            if not await wait_until_running(session, conversation_id):
                return None

            async def get_conversation_by_id_fn(cid: UUID):
                return await adapter.get_by_id(session, cid)

            async def list_messages_fn(cid: UUID):
                return await adapter.list_messages(session, cid)

            async def append_messages_fn(cid: UUID, messages: Sequence[Message]):
                return await adapter.append_messages(session, cid, messages)

            async def save_turn_state_fn(cid: UUID, turn: TurnState):
                return await adapter.save_turn_state(session, cid, turn)

            status = await conversations_use_cases.advance_turn(
                conversation_id=conversation_id,
                llm=llm,
                executor=Executor({}, DenyGate()),
                get_conversation_by_id_fn=get_conversation_by_id_fn,
                list_messages_fn=list_messages_fn,
                append_messages_fn=append_messages_fn,
                save_turn_state_fn=save_turn_state_fn,
            )
            await session.commit()
            return status
        except Exception:
            await session.rollback()
            await _mark_failed(conversation_id)
            raise


async def _mark_failed(conversation_id: UUID) -> None:
    async with async_session_factory() as session:
        await adapter.save_turn_state(
            session, conversation_id, TurnState(status=ConversationStatus.FAILED)
        )
        await session.commit()

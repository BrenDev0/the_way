import asyncio
from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import TaskiqDepends

from src.api_keys import use_cases as api_keys_use_cases
from src.api_keys.sqlalchemy import adapter as api_keys_adapter
from src.core.cryptography.ports import EncryptionService
from src.core.database.sqlalchemy.core import async_session_factory
from src.core.llm.domain import Message
from src.core.llm.ports import LLM
from src.core.tasks.broker import broker
from src.core.tools.executor import Executor
from src.core.tools.gates import DenyGate
from src.knowledge import tools as knowledge_tools
from src.worker import dependencies as worker_dependencies

from . import providers as conversations_providers
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
    encryption_service: Annotated[
        EncryptionService,
        TaskiqDepends(worker_dependencies.get_encryption_service),
    ],
) -> str | None:
    return await run_turn(conversation_id, encryption_service=encryption_service)


async def build_llm_for_user(
    session: AsyncSession,
    user_id: UUID,
    encryption_service: EncryptionService,
) -> LLM:
    async def list_api_keys_for_user_fn(uid: UUID):
        return await api_keys_adapter.list_for_user(session, uid)

    credential = await api_keys_use_cases.resolve_llm_credential(
        user_id=user_id,
        list_api_keys_for_user_fn=list_api_keys_for_user_fn,
    )
    return conversations_providers.provide_llm(
        model=api_keys_use_cases.model_for(credential),
        api_key=encryption_service.decrypt(credential.encrypted_secret),
    )


async def run_turn(
    conversation_id: UUID,
    encryption_service: EncryptionService | None = None,
    llm: LLM | None = None,
) -> str | None:
    async with async_session_factory() as session:
        try:
            if not await wait_until_running(session, conversation_id):
                return None

            conversation = await adapter.get_by_id(session, conversation_id)
            if conversation is None:
                return None

            if llm is None:
                if encryption_service is None:
                    raise ValueError("run_turn needs an encryption service or an llm")
                llm = await build_llm_for_user(
                    session, conversation.user_id, encryption_service
                )

            async def build_knowledge_context_fn(organization_id: UUID) -> str:
                return await knowledge_tools.build_context(session, organization_id)

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
                executor=Executor(
                    knowledge_tools.build(session, conversation.organization_id),
                    DenyGate(),
                ),
                get_conversation_by_id_fn=get_conversation_by_id_fn,
                list_messages_fn=list_messages_fn,
                append_messages_fn=append_messages_fn,
                save_turn_state_fn=save_turn_state_fn,
                build_knowledge_context_fn=build_knowledge_context_fn,
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

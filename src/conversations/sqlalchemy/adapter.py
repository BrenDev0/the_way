from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.conversations.domain import Conversation, ConversationCreate, TurnState
from src.core.llm.domain import Message

from . import mapper
from .models import ConversationRow, MessageRow


async def create(session: AsyncSession, conversation: ConversationCreate) -> Conversation:
    row = mapper.domain_create_to_row(conversation)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def get_for_user(
    session: AsyncSession,
    conversation_id: UUID,
    user_id: UUID,
) -> Conversation | None:
    result = await session.execute(
        select(ConversationRow).where(
            ConversationRow.id == conversation_id,
            ConversationRow.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()

    return mapper.row_to_domain(row) if row else None


async def get_by_id(session: AsyncSession, conversation_id: UUID) -> Conversation | None:
    result = await session.execute(
        select(ConversationRow).where(ConversationRow.id == conversation_id)
    )
    row = result.scalar_one_or_none()

    return mapper.row_to_domain(row) if row else None


async def list_messages(session: AsyncSession, conversation_id: UUID) -> list[Message]:
    result = await session.execute(
        select(MessageRow)
        .where(MessageRow.conversation_id == conversation_id)
        .order_by(MessageRow.position)
    )
    return [mapper.message_row_to_domain(row) for row in result.scalars().all()]


async def list_for_user(session: AsyncSession, user_id: UUID) -> Sequence[Conversation]:
    result = await session.execute(
        select(ConversationRow)
        .where(ConversationRow.user_id == user_id)
        .order_by(ConversationRow.updated_at.desc())
    )
    return [mapper.row_to_domain(row) for row in result.scalars().all()]


async def delete_for_user(
    session: AsyncSession,
    conversation_id: UUID,
    user_id: UUID,
) -> bool:
    result = await session.execute(
        delete(ConversationRow)
        .where(
            ConversationRow.id == conversation_id,
            ConversationRow.user_id == user_id,
        )
        .returning(ConversationRow.id)
    )
    return result.scalar_one_or_none() is not None


async def list_messages_for_user(
    session: AsyncSession,
    conversation_id: UUID,
    user_id: UUID,
) -> list[Message] | None:
    owned = await session.execute(
        select(ConversationRow.id).where(
            ConversationRow.id == conversation_id,
            ConversationRow.user_id == user_id,
        )
    )
    if owned.scalar_one_or_none() is None:
        return None

    result = await session.execute(
        select(MessageRow)
        .where(MessageRow.conversation_id == conversation_id)
        .order_by(MessageRow.position)
    )
    return [mapper.message_row_to_domain(row) for row in result.scalars().all()]


async def save_turn_state(
    session: AsyncSession,
    conversation_id: UUID,
    turn: TurnState,
) -> Conversation | None:
    result = await session.execute(
        select(ConversationRow).where(ConversationRow.id == conversation_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None

    mapper.apply_turn_state(row, turn)
    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def append_messages(
    session: AsyncSession,
    conversation_id: UUID,
    messages: Sequence[Message],
) -> int:
    if not messages:
        return 0

    result = await session.execute(
        select(func.coalesce(func.max(MessageRow.position), -1)).where(
            MessageRow.conversation_id == conversation_id
        )
    )
    next_position = result.scalar_one() + 1

    session.add_all(
        [
            mapper.message_to_row(conversation_id, next_position + offset, message)
            for offset, message in enumerate(messages)
        ]
    )
    await session.flush()
    return len(messages)

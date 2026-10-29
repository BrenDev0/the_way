from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Text, cast, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.conversations.domain import (
    Conversation,
    ConversationCreate,
    ConversationFolder,
    ConversationStatus,
    TurnState,
)
from src.core.llm.domain import Message

from . import mapper
from .models import ConversationFolderRow, ConversationRow, MessageRow


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


async def rename(session: AsyncSession, conversation_id: UUID, title: str) -> Conversation | None:
    row = await session.get(ConversationRow, conversation_id)
    if row is None:
        return None
    row.title = title
    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


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


# --- a person's folders for their chats -----------------------------------------------


async def list_folders(session: AsyncSession, user_id: UUID) -> Sequence[ConversationFolder]:
    result = await session.execute(
        select(ConversationFolderRow)
        .where(ConversationFolderRow.user_id == user_id)
        .order_by(func.lower(ConversationFolderRow.name), ConversationFolderRow.created_at)
    )
    return [mapper.folder_to_domain(row) for row in result.scalars().all()]


async def count_folders(session: AsyncSession, user_id: UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(ConversationFolderRow).where(ConversationFolderRow.user_id == user_id)
    )
    return int(result.scalar_one())


async def find_folder_by_name(session: AsyncSession, user_id: UUID, name: str) -> ConversationFolder | None:
    result = await session.execute(
        select(ConversationFolderRow).where(
            ConversationFolderRow.user_id == user_id,
            func.lower(ConversationFolderRow.name) == name.lower(),
        )
    )
    row = result.scalars().first()
    return mapper.folder_to_domain(row) if row else None


async def get_folder(session: AsyncSession, folder_id: UUID, user_id: UUID) -> ConversationFolder | None:
    result = await session.execute(
        select(ConversationFolderRow).where(
            ConversationFolderRow.id == folder_id, ConversationFolderRow.user_id == user_id
        )
    )
    row = result.scalar_one_or_none()
    return mapper.folder_to_domain(row) if row else None


async def create_folder(session: AsyncSession, user_id: UUID, name: str) -> ConversationFolder:
    row = ConversationFolderRow(user_id=user_id, name=name)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return mapper.folder_to_domain(row)


async def rename_folder(
    session: AsyncSession, folder_id: UUID, user_id: UUID, name: str
) -> ConversationFolder | None:
    result = await session.execute(
        select(ConversationFolderRow).where(
            ConversationFolderRow.id == folder_id, ConversationFolderRow.user_id == user_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    row.name = name
    await session.flush()
    await session.refresh(row)
    return mapper.folder_to_domain(row)


async def delete_folder(session: AsyncSession, folder_id: UUID, user_id: UUID) -> bool:
    result = await session.execute(
        delete(ConversationFolderRow)
        .where(ConversationFolderRow.id == folder_id, ConversationFolderRow.user_id == user_id)
        .returning(ConversationFolderRow.id)
    )
    return result.scalar_one_or_none() is not None


async def move_to_folder(
    session: AsyncSession, conversation_id: UUID, user_id: UUID, folder_id: UUID | None
) -> Conversation | None:
    # updated_at is kept as it is: filing a chat is not activity in it, and must not float it to the top
    result = await session.execute(
        update(ConversationRow)
        .where(ConversationRow.id == conversation_id, ConversationRow.user_id == user_id)
        .values(folder_id=folder_id, updated_at=ConversationRow.updated_at)
        .returning(ConversationRow.id)
    )
    if result.scalar_one_or_none() is None:
        return None
    return await get_for_user(session, conversation_id, user_id)


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


async def search_messages(
    session: AsyncSession,
    user_id: UUID,
    terms: Sequence[str],
    limit: int,
) -> list[tuple[Message, Any]]:
    """The user's own chat messages containing any of the terms, newest first, with when
    each was written. Candidates only -- ranking them is the caller's job."""
    if not terms:
        return []

    text = cast(MessageRow.content, Text)
    result = await session.execute(
        select(MessageRow)
        .join(ConversationRow, ConversationRow.id == MessageRow.conversation_id)
        .where(
            ConversationRow.user_id == user_id,
            MessageRow.role.in_(("user", "assistant")),
            or_(*(text.ilike(f"%{term}%") for term in terms)),
        )
        .order_by(MessageRow.created_at.desc())
        .limit(limit)
    )
    return [(mapper.message_row_to_domain(row), row.created_at) for row in result.scalars().all()]


async def claim_if_idle(session: AsyncSession, conversation_id: UUID) -> Conversation | None:
    """Starts a turn on a conversation only if nothing is happening on it -- in one
    statement, so two things that both find it idle cannot both start one."""
    result = await session.execute(
        update(ConversationRow)
        .where(ConversationRow.id == conversation_id, ConversationRow.status == ConversationStatus.IDLE)
        .values(status=ConversationStatus.RUNNING, iterations_used=0)
        .returning(ConversationRow.id)
    )
    if result.scalar_one_or_none() is None:
        return None
    return await get_by_id(session, conversation_id)


async def claim_turn(session: AsyncSession, conversation_id: UUID, run: str) -> bool:
    """Takes the running turn for one queue message -- unless another holds it. The
    message that held it may take it again: the queue redelivers a message whose worker
    died, and that turn is carried on from its last checkpoint."""
    result = await session.execute(
        update(ConversationRow)
        .where(
            ConversationRow.id == conversation_id,
            ConversationRow.status == ConversationStatus.RUNNING,
            or_(ConversationRow.run_claim.is_(None), ConversationRow.run_claim == run),
        )
        .values(run_claim=run)
        .returning(ConversationRow.id)
    )
    return result.scalar_one_or_none() is not None


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

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.sqlalchemy.models import Base, IDMixin, TimestampMixin


class ConversationRow(Base, IDMixin, TimestampMixin):
    __tablename__ = "conversations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    client: Mapped[str] = mapped_column(String(16), nullable=False, default="desktop")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    pending_tool_calls: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    completed_tool_results: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    tool_decisions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    iterations_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # why the turn is paused, while it is
    pause_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pause_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The queue message running the turn, while it runs. A message the queue delivers again
    # (its worker died) carries the same id and may carry on; any other finds it taken.
    run_claim: Mapped[str | None] = mapped_column(String(64), nullable=True)


class MessageRow(Base, IDMixin, TimestampMixin):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "position", name="uq_message_position"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[Any] = mapped_column(JSONB, nullable=False)
    tool_calls: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.sqlalchemy.models import Base, IDMixin, TimestampMixin


class BackgroundTaskRow(Base, IDMixin, TimestampMixin):
    __tablename__ = "background_tasks"

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
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    folder: Mapped[str] = mapped_column(String(128), nullable=False)
    deliver_project: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deliver_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    reported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The worker's own tool calls, by name with their arguments clipped -- what it read and
    # did. A conversation's calls are in its messages; a worker's were kept nowhere.
    tool_calls: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.sqlalchemy.models import Base, IDMixin, TimestampMixin


class SkillRow(Base, IDMixin, TimestampMixin):
    __tablename__ = "skills"
    # A name is unique among the organization's own skills (no owner) and among one person's.
    __table_args__ = (
        Index(
            "uq_skill_organization_name", "organization_id", "name",
            unique=True, postgresql_where=text("owner_id IS NULL"),
        ),
        Index(
            "uq_skill_owner_name", "owner_id", "name",
            unique=True, postgresql_where=text("owner_id IS NOT NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    triggers: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    files: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # None: the organization's skill, seen by everyone in it. Set: that person's own.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

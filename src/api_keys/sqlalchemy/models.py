import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.sqlalchemy.models import Base, IDMixin, TimestampMixin


class ApiKeyRow(Base, IDMixin, TimestampMixin):
    """One key per provider per organization, set by Xplorers staff."""

    __tablename__ = "api_keys"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider", name="uq_api_key_organization_provider"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    secret: Mapped[str] = mapped_column(String, nullable=False)
    last_four: Mapped[str] = mapped_column(String(4), nullable=False)
    account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    set_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="SET NULL"),
        nullable=True,
    )

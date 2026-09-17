import uuid

from sqlalchemy import String, ForeignKey, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.sqlalchemy.models import Base, IDMixin, TimestampMixin


class UserRow(Base, IDMixin, TimestampMixin):
    __tablename__ = "users"

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    email_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    password: Mapped[str] = mapped_column(String, nullable=False)

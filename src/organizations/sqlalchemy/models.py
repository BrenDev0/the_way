from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.sqlalchemy.models import Base, IDMixin, TimestampMixin


class OrganizationRow(Base, IDMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    seat_limit: Mapped[int | None] = mapped_column(nullable=True)

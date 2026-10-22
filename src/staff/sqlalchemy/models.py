import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.sqlalchemy.models import Base, IDMixin, TimestampMixin


class StaffMemberRow(Base, IDMixin, TimestampMixin):
    __tablename__ = "staff_members"

    email: Mapped[str] = mapped_column(String, nullable=False)
    email_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    password: Mapped[str] = mapped_column(String, nullable=False)


class StaffSessionRow(Base, IDMixin, TimestampMixin):
    __tablename__ = "staff_sessions"

    staff_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class OwnerInvitationRow(Base, IDMixin, TimestampMixin):
    __tablename__ = "owner_invitations"

    organization_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    email_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    seat_limit: Mapped[int | None] = mapped_column(nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Filled in when the invitation is accepted. If that organization is ever deleted, the
    # record of the invitation stays.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class DeletedOrganizationRow(Base, IDMixin, TimestampMixin):
    """The record kept when staff delete an organization. No foreign key to it: the
    organization is gone, and this is what remains to say it was there."""

    __tablename__ = "deleted_organizations"

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    organization_name: Mapped[str] = mapped_column(String(255), nullable=False)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="SET NULL"),
        nullable=True,
    )
    # kept as text, encrypted like every email, so it still says who after that person is removed
    deleted_by_email: Mapped[str] = mapped_column(String, nullable=False)
    members: Mapped[int] = mapped_column(nullable=False)
    files: Mapped[int] = mapped_column(nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    files_removed: Mapped[int] = mapped_column(nullable=False)
    files_left: Mapped[int | None] = mapped_column(nullable=True)

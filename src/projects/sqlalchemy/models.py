import uuid

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, String, false, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.sqlalchemy.models import Base, IDMixin, TimestampMixin


class ProjectRow(Base, IDMixin, TimestampMixin):
    __tablename__ = "projects"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Survives the owner's account being deleted so an owner or admin can
    # reassign or clean it up.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # The organization's library: one per organization, no owner, read by every member
    # and changed only by owners and admins. Not the same as an orphan, whose owner_id is
    # also empty but which nobody else may read.
    shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())


class FolderRow(Base, IDMixin, TimestampMixin):
    __tablename__ = "project_folders"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_folders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class FileRow(Base, IDMixin, TimestampMixin):
    __tablename__ = "project_files"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_folders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


# Names are unique case-insensitively so a tree always syncs to a Windows or
# macOS disk. NULLS NOT DISTINCT makes the project root count as one folder.
Index(
    "uq_project_owner_name",
    ProjectRow.owner_id,
    func.lower(ProjectRow.name),
    unique=True,
)
# One library per organization, however many requests create it at once.
Index(
    "uq_project_library_per_organization",
    ProjectRow.organization_id,
    unique=True,
    postgresql_where=ProjectRow.shared,
)
Index(
    "uq_project_folder_parent_name",
    FolderRow.project_id,
    FolderRow.parent_id,
    func.lower(FolderRow.name),
    unique=True,
    postgresql_nulls_not_distinct=True,
)
Index(
    "uq_project_file_folder_name",
    FileRow.project_id,
    FileRow.folder_id,
    func.lower(FileRow.name),
    unique=True,
    postgresql_nulls_not_distinct=True,
)

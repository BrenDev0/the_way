from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass
class Organization:
    id: UUID
    name: str
    seat_limit: int | None
    created_at: datetime
    updated_at: datetime


@dataclass
class OrganizationCreate:
    name: str
    seat_limit: int | None = None


# --- the organization at a glance: read models, built from other slices' data ---------


@dataclass(frozen=True)
class ProjectStorage:
    """A project's footprint: the files that finished uploading, and their total size."""

    id: UUID
    name: str
    owner_id: UUID | None
    shared: bool
    updated_at: datetime
    files: int
    bytes: int


@dataclass(frozen=True)
class PersonStorage:
    """What one member's projects add up to."""

    user_id: UUID
    projects: int
    files: int
    bytes: int


@dataclass(frozen=True)
class OrganizationOverview:
    """Seats in use, who owns the organization, where the storage goes, and the projects
    left without an owner when someone was removed."""

    seat_limit: int | None
    members: int
    pending_invitations: int
    owner_id: UUID | None
    total_files: int
    total_bytes: int
    library: ProjectStorage | None
    by_person: Sequence[PersonStorage]  # biggest first
    largest: Sequence[ProjectStorage]  # members' own projects, biggest first
    orphans: Sequence[ProjectStorage]


@dataclass(frozen=True)
class MonthlyUsage:
    """One person's AI use in one calendar month."""

    user_id: UUID
    month: date  # its first day
    conversations: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int


@dataclass(frozen=True)
class UsageReport:
    months: Sequence[date]  # the first day of each month asked for, oldest first
    rows: Sequence[MonthlyUsage]


@dataclass(frozen=True)
class FilesPurged:
    """What deleting an organization's stored files did: how many went, and how many could not."""

    removed: int
    failed: int

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field

from src.fastapi.schemas import ApiBaseModel

from ..domain import (
    MonthlyUsage,
    Organization,
    OrganizationOverview,
    PersonStorage,
    ProjectStorage,
    UsageReport,
)


class OrganizationResponse(ApiBaseModel):
    id: UUID
    name: str
    seat_limit: int | None
    created_at: datetime

    @classmethod
    def from_domain(cls, organization: Organization) -> Self:
        return cls(
            id=organization.id,
            name=organization.name,
            seat_limit=organization.seat_limit,
            created_at=organization.created_at,
        )


class UpdateOrganizationRequest(ApiBaseModel):
    name: str


class DeleteOrganizationResponse(ApiBaseModel):
    detail: str


class TransferOwnershipRequest(ApiBaseModel):
    new_owner_id: UUID


class TransferOwnershipResponse(ApiBaseModel):
    detail: str


# --- the organization at a glance ---------------------------------------------------
# Ids and dates travel as strings, exactly as the panel has always read them.


class SeatsResponse(ApiBaseModel):
    limit: int | None
    members: int
    pending: int


class LibraryStorageResponse(ApiBaseModel):
    files: int
    bytes: int


class ProjectStorageResponse(ApiBaseModel):
    id: str
    # a project may be called "a": the base model's two-character minimum does not apply
    name: str = Field(min_length=1)
    owner_id: str | None
    shared: bool
    updated_at: str
    files: int
    bytes: int

    @classmethod
    def from_domain(cls, project: ProjectStorage) -> Self:
        return cls(
            id=str(project.id),
            name=project.name,
            owner_id=str(project.owner_id) if project.owner_id else None,
            shared=project.shared,
            updated_at=project.updated_at.isoformat(),
            files=project.files,
            bytes=project.bytes,
        )


class PersonStorageResponse(ApiBaseModel):
    id: str
    projects: int
    files: int
    bytes: int

    @classmethod
    def from_domain(cls, person: PersonStorage) -> Self:
        return cls(
            id=str(person.user_id),
            projects=person.projects,
            files=person.files,
            bytes=person.bytes,
        )


class StorageResponse(ApiBaseModel):
    bytes: int
    files: int
    library: LibraryStorageResponse | None
    by_person: list[PersonStorageResponse]
    largest: list[ProjectStorageResponse]


class OrganizationOverviewResponse(ApiBaseModel):
    seats: SeatsResponse
    owner_id: str | None
    storage: StorageResponse
    orphans: list[ProjectStorageResponse]

    @classmethod
    def from_domain(cls, overview: OrganizationOverview) -> Self:
        library = overview.library
        return cls(
            seats=SeatsResponse(
                limit=overview.seat_limit,
                members=overview.members,
                pending=overview.pending_invitations,
            ),
            owner_id=str(overview.owner_id) if overview.owner_id else None,
            storage=StorageResponse(
                bytes=overview.total_bytes,
                files=overview.total_files,
                library=(
                    LibraryStorageResponse(files=library.files, bytes=library.bytes)
                    if library is not None
                    else None
                ),
                by_person=[PersonStorageResponse.from_domain(p) for p in overview.by_person],
                largest=[ProjectStorageResponse.from_domain(p) for p in overview.largest],
            ),
            orphans=[ProjectStorageResponse.from_domain(p) for p in overview.orphans],
        )


class UsageRowResponse(ApiBaseModel):
    user_id: str
    month: str
    conversations: int
    input: int
    output: int
    cache_read: int
    cache_write: int

    @classmethod
    def from_domain(cls, usage: MonthlyUsage) -> Self:
        return cls(
            user_id=str(usage.user_id),
            month=usage.month.isoformat(),
            conversations=usage.conversations,
            input=usage.input_tokens,
            output=usage.output_tokens,
            cache_read=usage.cache_read_tokens,
            cache_write=usage.cache_write_tokens,
        )


class UsageResponse(ApiBaseModel):
    months: list[str]
    rows: list[UsageRowResponse]

    @classmethod
    def from_domain(cls, report: UsageReport) -> Self:
        return cls(
            months=[month.isoformat() for month in report.months],
            rows=[UsageRowResponse.from_domain(row) for row in report.rows],
        )

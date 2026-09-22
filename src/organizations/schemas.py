from datetime import datetime
from uuid import UUID

from src.core.schemas import ApiBaseModel


class OrganizationResponse(ApiBaseModel):
    id: UUID
    name: str
    seat_limit: int | None
    created_at: datetime


class UpdateOrganizationRequest(ApiBaseModel):
    name: str


class DeleteOrganizationResponse(ApiBaseModel):
    detail: str


class TransferOwnershipRequest(ApiBaseModel):
    new_owner_id: UUID


class TransferOwnershipResponse(ApiBaseModel):
    detail: str

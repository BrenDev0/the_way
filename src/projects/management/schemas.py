from uuid import UUID

from src.core.schemas import ApiBaseModel


class TransferProjectRequest(ApiBaseModel):
    new_owner_id: UUID

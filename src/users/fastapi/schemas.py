from datetime import datetime
from typing import Self
from uuid import UUID

from src.fastapi.schemas import ApiBaseModel

from ..domain import Role, User


class UserResponse(ApiBaseModel):
    id: UUID
    organization_id: UUID
    email: str
    role: Role
    setup_complete: bool
    created_at: datetime

    @classmethod
    def from_domain(cls, user: User, email: str, setup_complete: bool) -> Self:
        """`email` is the decrypted address: the user is stored with it encrypted, and
        decrypting is the caller's job, so this schema never needs the encryption port."""
        return cls(
            id=user.id,
            organization_id=user.organization_id,
            email=email,
            role=user.role,
            setup_complete=setup_complete,
            created_at=user.created_at,
        )


class DeleteUserResponse(ApiBaseModel):
    detail: str

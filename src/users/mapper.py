from datetime import datetime
from typing import Any
from uuid import UUID

from src.core.cryptography.ports import EncryptionService

from .domain import Role, User
from .schemas import UserResponse


def domain_to_user_response(user: User, encryption_service: EncryptionService) -> UserResponse:
    return UserResponse(
        id=user.id,
        organization_id=user.organization_id,
        email=encryption_service.decrypt(user.encrypted_email),
        role=user.role,
        created_at=user.created_at,
    )


def domain_to_cache(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "organization_id": str(user.organization_id),
        "encrypted_email": user.encrypted_email,
        "email_hash": user.email_hash,
        "password_hash": user.password_hash,
        "role": str(user.role),
        "created_at": user.created_at.isoformat(),
    }


def cache_to_domain(data: dict[str, Any]) -> User:
    return User(
        id=UUID(data["id"]),
        organization_id=UUID(data["organization_id"]),
        encrypted_email=data["encrypted_email"],
        email_hash=data["email_hash"],
        password_hash=data["password_hash"],
        role=Role(data["role"]),
        created_at=datetime.fromisoformat(data["created_at"]),
    )

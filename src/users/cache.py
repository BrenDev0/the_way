from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from .domain import Role, User

CACHE_TTL_SECONDS = 60 * 5


class UserCacheKey(StrEnum):
    BY_ID = "users:by_id"


def build_user_cache_key(key: UserCacheKey, user_id: UUID) -> str:
    return f"{key}:{user_id}"


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

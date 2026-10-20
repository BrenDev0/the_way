from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from .domain import Organization

CACHE_TTL_SECONDS = 60 * 5


class OrganizationCacheKey(StrEnum):
    BY_ID = "organizations:by_id"


def build_organization_cache_key(key: OrganizationCacheKey, organization_id: UUID) -> str:
    return f"{key}:{organization_id}"


def domain_to_cache(organization: Organization) -> dict[str, Any]:
    return {
        "id": str(organization.id),
        "name": organization.name,
        "seat_limit": organization.seat_limit,
        "created_at": organization.created_at.isoformat(),
        "updated_at": organization.updated_at.isoformat(),
    }


def cache_to_domain(data: dict[str, Any]) -> Organization:
    return Organization(
        id=UUID(data["id"]),
        name=data["name"],
        seat_limit=data["seat_limit"],
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
    )

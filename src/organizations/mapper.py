from datetime import datetime
from typing import Any
from uuid import UUID

from .domain import Organization
from .schemas import OrganizationResponse


def domain_to_organization_response(organization: Organization) -> OrganizationResponse:
    return OrganizationResponse(
        id=organization.id,
        name=organization.name,
        seat_limit=organization.seat_limit,
        created_at=organization.created_at,
    )


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

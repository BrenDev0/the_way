from enum import StrEnum
from uuid import UUID

CACHE_TTL_SECONDS = 60 * 5


class OrganizationCacheKey(StrEnum):
    BY_ID = "organizations:by_id"


def build_organization_cache_key(key: OrganizationCacheKey, organization_id: UUID) -> str:
    return f"{key}:{organization_id}"

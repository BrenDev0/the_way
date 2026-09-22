from enum import StrEnum
from uuid import UUID

CACHE_TTL_SECONDS = 60 * 5


class UserCacheKey(StrEnum):
    BY_ID = "users:by_id"


def build_user_cache_key(key: UserCacheKey, user_id: UUID) -> str:
    return f"{key}:{user_id}"

from enum import StrEnum


class AuthCacheKey(StrEnum):
    VERIFICATION_CODE = "auth:registration:verification_code"
    VERIFICATION_ATTEMPTS = "auth:registration:attempts"
    VERIFICATION_COOLDOWN = "auth:registration:cooldown"
    VERIFICATION_REQUESTS = "auth:registration:requests"


def build_auth_cache_key(key: AuthCacheKey, email_hash: str) -> str:
    return f"{key}:{email_hash}"

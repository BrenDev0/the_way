from enum import StrEnum


class AuthCacheKey(StrEnum):
    VERIFICATION_CODE = "auth:registration:verification_code"
    VERIFICATION_ATTEMPTS = "auth:registration:attempts"
    VERIFICATION_COOLDOWN = "auth:registration:cooldown"
    VERIFICATION_REQUESTS = "auth:registration:requests"
    DESKTOP_LOGIN_FAILURES_EMAIL = "auth:desktop_login:failures:email"
    DESKTOP_LOGIN_FAILURES_IP = "auth:desktop_login:failures:ip"


def build_auth_cache_key(key: AuthCacheKey, email_hash: str) -> str:
    return f"{key}:{email_hash}"

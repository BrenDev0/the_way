from enum import StrEnum


class AuthCacheKey(StrEnum):
    DESKTOP_LOGIN_FAILURES_EMAIL = "auth:desktop_login:failures:email"
    DESKTOP_LOGIN_FAILURES_IP = "auth:desktop_login:failures:ip"


def build_auth_cache_key(key: AuthCacheKey, email_hash: str) -> str:
    return f"{key}:{email_hash}"

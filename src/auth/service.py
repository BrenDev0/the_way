from src.core.cache.ports import CacheStore
from src.core.exceptions import RateLimitError
from src.core.settings.api import settings as api_settings

from .cache import AuthCacheKey, build_auth_cache_key


def _desktop_login_keys(email_hash: str, client_ip: str) -> tuple[tuple[str, int], ...]:
    return (
        (
            build_auth_cache_key(AuthCacheKey.DESKTOP_LOGIN_FAILURES_EMAIL, email_hash),
            api_settings.DESKTOP_LOGIN_MAX_FAILURES_PER_EMAIL,
        ),
        (
            build_auth_cache_key(AuthCacheKey.DESKTOP_LOGIN_FAILURES_IP, client_ip),
            api_settings.DESKTOP_LOGIN_MAX_FAILURES_PER_IP,
        ),
    )


async def ensure_desktop_login_allowed(
    email_hash: str, client_ip: str, cache_store: CacheStore
) -> None:
    """Refuse a login attempt once an email or an address has failed too often.

    Desktop login is the one route reachable straight from the internet without the front
    end's signature in front of it, so guessing passwords against it is capped two ways:
    per email (one account being guessed) and per address (many accounts from one place).
    Only failures count, and the window starts at the first one.
    """
    for key, limit in _desktop_login_keys(email_hash, client_ip):
        failures = await cache_store.get_int(key)
        if failures is not None and failures >= limit:
            raise RateLimitError(
                message="Too many failed sign-in attempts. Please wait before trying again",
                code="login_rate_limited",
            )


async def record_desktop_login_failure(
    email_hash: str, client_ip: str, cache_store: CacheStore
) -> None:
    for key, _ in _desktop_login_keys(email_hash, client_ip):
        if await cache_store.increment(key) == 1:
            await cache_store.expire(key, api_settings.DESKTOP_LOGIN_WINDOW_SECONDS)


async def clear_desktop_login_failures(email_hash: str, cache_store: CacheStore) -> None:
    await cache_store.remove(
        build_auth_cache_key(AuthCacheKey.DESKTOP_LOGIN_FAILURES_EMAIL, email_hash)
    )

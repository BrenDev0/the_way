from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from secrets import choice
from string import digits

from src.core.cache.ports import CacheStore
from src.core.exceptions import (
    AuthenticationError,
    ConflictError,
    InternalServerError,
    RateLimitError,
)
from src.core.settings import settings

from .cache import AuthCacheKey, build_auth_cache_key

DEFAULT_VERIFICATION_CODE_LENGTH = 6


def generate_numeric_code(length: int = DEFAULT_VERIFICATION_CODE_LENGTH) -> str:
    return "".join(choice(digits) for _ in range(length))


async def issue_registration_verification_code(
    email_hash: str,
    cache_store: CacheStore,
    code_hash_fn: Callable[[str], str],
    code_generator: Callable[[int], str] = generate_numeric_code,
) -> tuple[str, datetime]:
    ttl_seconds = settings.REGISTRATION_VERIFICATION_CODE_TTL_SECONDS

    cooldown_key = build_auth_cache_key(AuthCacheKey.VERIFICATION_COOLDOWN, email_hash)
    if await cache_store.get_bool(cooldown_key):
        raise ConflictError(
            message="Too many verification requests. Please wait before trying again",
            code="verification_request_cooldown_active",
        )

    requests_key = build_auth_cache_key(AuthCacheKey.VERIFICATION_REQUESTS, email_hash)
    request_count = await cache_store.increment(requests_key)
    if request_count == 1:
        await cache_store.expire(requests_key, ttl_seconds)

    if request_count > settings.REGISTRATION_VERIFICATION_MAX_REQUESTS:
        await cache_store.store_bool(
            cooldown_key,
            True,
            settings.REGISTRATION_VERIFICATION_COOLDOWN_SECONDS,
        )
        raise ConflictError(
            message="Too many verification requests. Please wait before trying again",
            code="verification_request_limit_reached",
        )

    raw_code = code_generator(DEFAULT_VERIFICATION_CODE_LENGTH)
    code_key = build_auth_cache_key(AuthCacheKey.VERIFICATION_CODE, email_hash)
    attempts_key = build_auth_cache_key(AuthCacheKey.VERIFICATION_ATTEMPTS, email_hash)

    stored_code = await cache_store.store_str(code_key, code_hash_fn(raw_code), ttl_seconds)
    if not stored_code:
        raise InternalServerError(
            message="Unable to process request at this time",
            code="verification_code_store_failed",
        )

    stored_attempts = await cache_store.store_int(attempts_key, 0, ttl_seconds)
    if not stored_attempts:
        await cache_store.remove(code_key)
        raise InternalServerError(
            message="Unable to process request at this time",
            code="verification_attempt_store_failed",
        )

    return raw_code, datetime.now(UTC) + timedelta(seconds=ttl_seconds)


def _desktop_login_keys(email_hash: str, client_ip: str) -> tuple[tuple[str, int], ...]:
    return (
        (
            build_auth_cache_key(AuthCacheKey.DESKTOP_LOGIN_FAILURES_EMAIL, email_hash),
            settings.DESKTOP_LOGIN_MAX_FAILURES_PER_EMAIL,
        ),
        (
            build_auth_cache_key(AuthCacheKey.DESKTOP_LOGIN_FAILURES_IP, client_ip),
            settings.DESKTOP_LOGIN_MAX_FAILURES_PER_IP,
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
            await cache_store.expire(key, settings.DESKTOP_LOGIN_WINDOW_SECONDS)


async def clear_desktop_login_failures(email_hash: str, cache_store: CacheStore) -> None:
    await cache_store.remove(
        build_auth_cache_key(AuthCacheKey.DESKTOP_LOGIN_FAILURES_EMAIL, email_hash)
    )


async def verify_registration_email_code(
    email_hash: str,
    submitted_code: str,
    cache_store: CacheStore,
    compare_code_hash_fn: Callable[[str, str], bool],
) -> None:
    code_key = build_auth_cache_key(AuthCacheKey.VERIFICATION_CODE, email_hash)
    attempts_key = build_auth_cache_key(AuthCacheKey.VERIFICATION_ATTEMPTS, email_hash)
    requests_key = build_auth_cache_key(AuthCacheKey.VERIFICATION_REQUESTS, email_hash)
    cooldown_key = build_auth_cache_key(AuthCacheKey.VERIFICATION_COOLDOWN, email_hash)

    stored_code_hash = await cache_store.get_str(code_key)
    if stored_code_hash is None:
        raise AuthenticationError(
            message="Verification code expired",
            code="verification_code_expired",
        )

    if compare_code_hash_fn(submitted_code, stored_code_hash):
        await cache_store.remove(code_key)
        await cache_store.remove(attempts_key)
        await cache_store.remove(requests_key)
        return

    attempts_used = await cache_store.increment(attempts_key)
    if attempts_used >= settings.REGISTRATION_VERIFICATION_MAX_ATTEMPTS:
        await cache_store.remove(code_key)
        await cache_store.remove(attempts_key)
        await cache_store.store_bool(
            cooldown_key,
            True,
            settings.REGISTRATION_VERIFICATION_COOLDOWN_SECONDS,
        )
        raise AuthenticationError(
            message="Too many invalid attempts",
            code="verification_attempt_limit_reached",
        )

    raise AuthenticationError(
        message="Invalid verification code",
        code="invalid_verification_code",
    )

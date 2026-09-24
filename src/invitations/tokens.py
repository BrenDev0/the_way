import secrets
from datetime import UTC, datetime, timedelta

from . import config


def generate_token() -> str:
    return secrets.token_urlsafe(config.TOKEN_BYTES)


def build_expiration(now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    return current + timedelta(seconds=config.INVITATION_TTL_SECONDS)


def ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

from datetime import UTC, datetime, timedelta
import hashlib
import secrets


class SessionTokenService:
    def __init__(self, session_ttl: timedelta | None = None):
        self.session_ttl = session_ttl or timedelta(days=7)

    def generate_session_token(self) -> str:
        return secrets.token_urlsafe(48)

    def hash_session_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def build_expiration(self, now: datetime | None = None) -> datetime:
        current_time = now or datetime.now(UTC)
        return current_time + self.session_ttl

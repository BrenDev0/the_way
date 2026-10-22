from dataclasses import dataclass

from src.core.settings.api import SameSitePolicy


@dataclass(frozen=True)
class SessionCookieConfig:
    name: str = "session"
    path: str = "/"
    secure: bool = True
    httponly: bool = True
    samesite: SameSitePolicy = "lax"
    max_age_seconds: int = 60 * 60 * 24 * 7

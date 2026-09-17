from dataclasses import dataclass


@dataclass(frozen=True)
class SessionCookieConfig:
    name: str = "session"
    path: str = "/"
    secure: bool = True
    httponly: bool = True
    samesite: str = "lax"
    max_age_seconds: int = 60 * 60 * 24 * 7

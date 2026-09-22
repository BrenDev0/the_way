from dataclasses import dataclass
from typing import Literal

SameSitePolicy = Literal["lax", "strict", "none"]


@dataclass(frozen=True)
class SessionCookieConfig:
    name: str = "session"
    path: str = "/"
    secure: bool = True
    httponly: bool = True
    samesite: SameSitePolicy = "lax"
    max_age_seconds: int = 60 * 60 * 24 * 7

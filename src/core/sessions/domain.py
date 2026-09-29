from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class SessionClient(StrEnum):
    # Carried in an httpOnly cookie, on routes that also demand the front end's signature.
    WEB = "web"
    # Carried as a bearer token by the desktop app, on the desktop routes only.
    DESKTOP = "desktop"


@dataclass
class Session:
    id: UUID
    user_id: UUID
    token_hash: str
    expires_at: datetime
    last_seen_at: datetime
    created_at: datetime
    revoked_at: datetime | None
    client: SessionClient = SessionClient.WEB
    device_name: str | None = None


@dataclass
class SessionCreate:
    user_id: UUID
    token_hash: str
    expires_at: datetime
    last_seen_at: datetime
    client: SessionClient = SessionClient.WEB
    device_name: str | None = None

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class Session:
    id: UUID
    user_id: UUID
    token_hash: str
    expires_at: datetime
    last_seen_at: datetime
    created_at: datetime
    revoked_at: datetime | None


@dataclass
class SessionCreate:
    user_id: UUID
    token_hash: str
    expires_at: datetime
    last_seen_at: datetime

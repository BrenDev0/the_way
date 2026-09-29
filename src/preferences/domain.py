from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class Preference:
    id: UUID
    organization_id: UUID
    user_id: UUID
    text: str
    created_at: datetime


@dataclass
class PreferenceCreate:
    organization_id: UUID
    user_id: UUID
    text: str

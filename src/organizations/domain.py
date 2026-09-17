from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class Organization:
    id: UUID
    name: str
    seat_limit: int | None
    created_at: datetime
    updated_at: datetime


@dataclass
class OrganizationCreate:
    name: str

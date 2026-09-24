from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class Skill:
    id: UUID
    organization_id: UUID
    name: str
    description: str
    instructions: str
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass
class SkillCreate:
    organization_id: UUID
    name: str
    description: str
    instructions: str
    created_by: UUID | None = None

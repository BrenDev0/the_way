from dataclasses import dataclass, field
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
    triggers: list[str] = field(default_factory=list)
    # None: the organization's skill. Set: this person's own, seen by no one else.
    owner_id: UUID | None = None
    # Reference files by relative path, e.g. {"laws.md": "..."}. None when the skill was
    # loaded in a listing, which leaves them behind: the index never needs their text.
    files: dict[str, str] | None = None
    # Their paths, which a listing does carry: the panel shows them without the text.
    file_names: list[str] = field(default_factory=list)


@dataclass
class SkillCreate:
    organization_id: UUID
    name: str
    description: str
    instructions: str
    created_by: UUID | None = None
    triggers: list[str] = field(default_factory=list)
    # None: for the whole organization. Set: this person's own.
    owner_id: UUID | None = None
    # None keeps the files the skill already has: saving from the editor sends only the
    # skill file, and must not wipe what an import put beside it.
    files: dict[str, str] | None = None

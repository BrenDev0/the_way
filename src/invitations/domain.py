from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.users.domain import Role

INVITABLE_BY: dict[Role, tuple[Role, ...]] = {
    Role.OWNER: (Role.ADMIN, Role.MEMBER),
    Role.ADMIN: (Role.MEMBER,),
    Role.MEMBER: (),
}


@dataclass
class Invitation:
    id: UUID
    organization_id: UUID
    encrypted_email: str
    email_hash: str
    role: Role
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    invited_by: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass
class InvitationCreate:
    organization_id: UUID
    encrypted_email: str
    email_hash: str
    role: Role
    token_hash: str
    expires_at: datetime
    invited_by: UUID | None = None

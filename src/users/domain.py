from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


@dataclass
class User:
    id: UUID
    organization_id: UUID
    encrypted_email: str
    email_hash: str
    password_hash: str
    role: Role
    created_at: datetime


@dataclass
class UserCreate:
    organization_id: UUID
    encrypted_email: str
    email_hash: str
    password_hash: str
    role: Role

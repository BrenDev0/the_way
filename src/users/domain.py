from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class User:
    id: UUID
    organization_id: UUID
    encrypted_email: str
    email_hash: str
    password_hash: str
    created_at: datetime


@dataclass
class UserCreate:
    organization_id: UUID
    encrypted_email: str
    email_hash: str
    password_hash: str

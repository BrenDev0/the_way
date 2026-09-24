from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class Provider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOHIGHLEVEL = "gohighlevel"


LLM_PROVIDERS = frozenset({Provider.ANTHROPIC, Provider.OPENAI})


@dataclass
class ApiKey:
    id: UUID
    organization_id: UUID
    user_id: UUID
    provider: Provider
    encrypted_secret: str
    last_four: str
    encrypted_account_id: str | None
    model: str | None
    issued_by: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass
class ApiKeyCreate:
    organization_id: UUID
    user_id: UUID
    provider: Provider
    encrypted_secret: str
    last_four: str
    encrypted_account_id: str | None = None
    model: str | None = None
    issued_by: UUID | None = None

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class Provider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOHIGHLEVEL = "gohighlevel"
    TAVILY = "tavily"


LLM_PROVIDERS = frozenset({Provider.ANTHROPIC, Provider.OPENAI})


@dataclass
class ApiKey:
    """A provider key (or the CX account) an organization works through. Xplorers sets it;
    every user of the organization uses it, and none of them sees it."""

    id: UUID
    organization_id: UUID
    provider: Provider
    encrypted_secret: str
    last_four: str
    encrypted_account_id: str | None
    model: str | None
    set_by: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass
class ApiKeyCreate:
    organization_id: UUID
    provider: Provider
    encrypted_secret: str
    last_four: str
    encrypted_account_id: str | None = None
    model: str | None = None
    set_by: UUID | None = None

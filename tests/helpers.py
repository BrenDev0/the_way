from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel

from src.api_keys.domain import ApiKey, Provider
from src.core.bucket.domain import RemoteObject
from src.core.llm.domain import Completion, Message, TokenUsage, ToolCall, assistant
from src.core.sessions.domain import Session
from src.documents.domain import Document, DocumentStatus
from src.organizations.domain import Organization
from src.skills.domain import Skill
from src.users.domain import Role, User


class FakeLLM:
    def __init__(self, *replies: Completion | str) -> None:
        self.replies = [
            reply if isinstance(reply, Completion) else make_completion(reply)
            for reply in replies
        ]
        self.received: list[list[Message]] = []
        self.tools_received: list[tuple[type[BaseModel], ...]] = []

    async def respond(self, messages: list[Message], tools: Sequence[type[BaseModel]] = ()) -> Completion:
        self.received.append(list(messages))
        self.tools_received.append(tuple(tools))
        if not self.replies:
            raise AssertionError("FakeLLM was called more times than it has replies")
        return self.replies.pop(0)


def make_completion(
    text: str = "",
    tool_calls: tuple[ToolCall, ...] = (),
    usage: TokenUsage | None = None,
) -> Completion:
    return Completion(
        message=assistant(text, tool_calls),
        text=text,
        tool_calls=tool_calls,
        usage=usage or TokenUsage(),
    )


class FakeCacheStore:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}
        self.store_str_succeeds = True
        self.store_int_succeeds = True

    async def store_json(self, key: str, data: dict[str, Any], expire_seconds: int) -> bool:
        self.data[key] = data
        self.ttls[key] = expire_seconds
        return True

    async def store_str(self, key: str, data: str, expire_seconds: int) -> bool:
        if not self.store_str_succeeds:
            return False
        self.data[key] = data
        self.ttls[key] = expire_seconds
        return True

    async def store_int(self, key: str, data: int, expire_seconds: int) -> bool:
        if not self.store_int_succeeds:
            return False
        self.data[key] = data
        self.ttls[key] = expire_seconds
        return True

    async def store_bool(self, key: str, data: bool, expire_seconds: int) -> bool:
        self.data[key] = data
        self.ttls[key] = expire_seconds
        return True

    async def get_json(self, key: str) -> dict[str, Any] | None:
        return self.data.get(key)

    async def get_str(self, key: str) -> str | None:
        return self.data.get(key)

    async def get_int(self, key: str) -> int | None:
        return self.data.get(key)

    async def get_bool(self, key: str) -> bool | None:
        return self.data.get(key)

    async def expire(self, key: str, expire_seconds: int) -> bool:
        self.ttls[key] = expire_seconds
        return True

    async def increment(self, key: str) -> int:
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    async def remove(self, key: str) -> bool:
        return self.data.pop(key, None) is not None


class FakeHashingService:
    def hash_password(self, password: str) -> str:
        return f"pwhash::{password}"

    def deterministic_hash(self, str_to_dhash: str) -> str:
        return f"dhash::{str_to_dhash}"

    def compare_password(self, password: str, hashed_value: str) -> bool:
        return hashed_value == f"pwhash::{password}"


class FakeEncryptionService:
    def encrypt(self, data: str | int) -> str:
        return f"enc::{data}"

    def decrypt(self, encrypted: str) -> str:
        return encrypted.removeprefix("enc::")


def make_user(
    *,
    user_id: UUID | None = None,
    organization_id: UUID | None = None,
    encrypted_email: str = "enc::user@example.com",
    email_hash: str = "dhash::user@example.com",
    password_hash: str = "pwhash::secret",
    role: Role = Role.MEMBER,
) -> User:
    return User(
        id=user_id or uuid4(),
        organization_id=organization_id or uuid4(),
        encrypted_email=encrypted_email,
        email_hash=email_hash,
        password_hash=password_hash,
        role=role,
        created_at=datetime.now(UTC),
    )


def make_organization(*, name: str = "Acme Inc", seat_limit: int | None = None) -> Organization:
    now = datetime.now(UTC)
    return Organization(
        id=uuid4(),
        name=name,
        seat_limit=seat_limit,
        created_at=now,
        updated_at=now,
    )


def make_session(
    *,
    user_id: UUID | None = None,
    token_hash: str = "token-hash",
    expires_in: timedelta = timedelta(days=1),
    revoked_at: datetime | None = None,
) -> Session:
    now = datetime.now(UTC)
    return Session(
        id=uuid4(),
        user_id=user_id or uuid4(),
        token_hash=token_hash,
        expires_at=now + expires_in,
        last_seen_at=now,
        created_at=now,
        revoked_at=revoked_at,
    )


def make_api_key(
    *,
    api_key_id: UUID | None = None,
    organization_id: UUID | None = None,
    user_id: UUID | None = None,
    provider: Provider = Provider.ANTHROPIC,
    encrypted_secret: str = "enc::sk-ant-secret1234",
    last_four: str = "1234",
    encrypted_account_id: str | None = None,
    model: str | None = None,
    issued_by: UUID | None = None,
) -> ApiKey:
    now = datetime.now(UTC)
    return ApiKey(
        id=api_key_id or uuid4(),
        organization_id=organization_id or uuid4(),
        user_id=user_id or uuid4(),
        provider=provider,
        encrypted_secret=encrypted_secret,
        last_four=last_four,
        encrypted_account_id=encrypted_account_id,
        model=model,
        issued_by=issued_by,
        created_at=now,
        updated_at=now,
    )


def make_document(
    *,
    document_id: UUID | None = None,
    organization_id: UUID | None = None,
    title: str = "Brand Book",
    description: str = "Visual identity and tone.",
    filename: str = "brand.pdf",
    content_type: str = "application/pdf",
    size_bytes: int = 1024,
    status: DocumentStatus = DocumentStatus.TRAINED,
    extracted_chars: int = 512,
    uploaded_by: UUID | None = None,
) -> Document:
    now = datetime.now(UTC)
    return Document(
        id=document_id or uuid4(),
        organization_id=organization_id or uuid4(),
        title=title,
        description=description,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        status=status,
        extracted_chars=extracted_chars,
        uploaded_by=uploaded_by,
        created_at=now,
        updated_at=now,
    )


def make_skill(
    *,
    skill_id: UUID | None = None,
    organization_id: UUID | None = None,
    name: str = "brand-voice",
    description: str = "How to write in the company voice.",
    instructions: str = "1. Be warm.\n2. Be plain.",
    created_by: UUID | None = None,
) -> Skill:
    now = datetime.now(UTC)
    return Skill(
        id=skill_id or uuid4(),
        organization_id=organization_id or uuid4(),
        name=name,
        description=description,
        instructions=instructions,
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )


class FakeBucketStore:
    def __init__(self, *, presign_url: str = "https://bucket.example/upload") -> None:
        self.objects: dict[str, int] = {}
        self.deleted: list[str] = []
        self.presigned: list[tuple[str, str, int]] = []
        self.presign_url = presign_url

    async def put(self, key: str, source):
        self.objects[key] = source.stat().st_size
        return RemoteObject(key=key, size=self.objects[key])

    async def get(self, key: str, destination):
        return destination

    async def list(self, prefix: str = "") -> list[RemoteObject]:
        return [
            RemoteObject(key=key, size=size)
            for key, size in sorted(self.objects.items())
            if key.startswith(prefix)
        ]

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def presign_put(self, key: str, content_type: str, expires_in: int) -> str:
        self.presigned.append((key, content_type, expires_in))
        return self.presign_url

    async def aclose(self) -> None:
        return None

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from src.core.llm.domain import Completion, Message, TokenUsage, ToolCall, assistant
from src.core.sessions.domain import Session
from src.organizations.domain import Organization
from src.users.domain import Role, User


class FakeLLM:
    def __init__(self, *replies: Completion | str) -> None:
        self.replies = [
            reply if isinstance(reply, Completion) else make_completion(reply)
            for reply in replies
        ]
        self.received: list[list[Message]] = []

    async def respond(self, messages: list[Message]) -> Completion:
        self.received.append(list(messages))
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

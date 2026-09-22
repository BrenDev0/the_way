import os

from cryptography.fernet import Fernet

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("CRYPTOGRAPHY_FERNET_KEY", Fernet.generate_key().decode("utf-8"))
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("REQUEST_SIGNING_SECRET", "test-signing-secret")
os.environ.setdefault("TASKIQ_BROKER_URL", "memory://")

import pytest
from helpers import FakeCacheStore, FakeEncryptionService, FakeHashingService


@pytest.fixture
def cache_store() -> FakeCacheStore:
    return FakeCacheStore()


@pytest.fixture
def hashing_service() -> FakeHashingService:
    return FakeHashingService()


@pytest.fixture
def encryption_service() -> FakeEncryptionService:
    return FakeEncryptionService()

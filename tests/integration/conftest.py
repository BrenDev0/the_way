import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import src.api_keys.sqlalchemy
import src.conversations.sqlalchemy
import src.core.sessions.sqlalchemy
import src.documents.sqlalchemy
import src.invitations.sqlalchemy
import src.organizations.sqlalchemy
import src.skills.sqlalchemy
import src.users.sqlalchemy  # noqa: F401
from src.core.database.sqlalchemy.models import Base
from src.core.settings import settings

NEEDS_SERVICES = (
    "Integration tests need the local stack. Run `docker compose up -d`, then "
    "`set -a && . ./.env && set +a && pytest tests/integration`."
)

INTEGRATION_DIR = Path(__file__).parent


def services_configured() -> bool:
    return settings.TASKIQ_BROKER_URL != "memory://"


def pytest_collection_modifyitems(config, items):
    if services_configured():
        return

    skip = pytest.mark.skip(reason=NEEDS_SERVICES)
    for item in items:
        if INTEGRATION_DIR in Path(str(item.path)).parents:
            item.add_marker(skip)


def build_engine():
    return create_async_engine(settings.DATABASE_URL, poolclass=NullPool)


@pytest.fixture(scope="session", autouse=True)
def schema():
    if not services_configured():
        yield
        return

    async def reset():
        engine = build_engine()
        try:
            async with engine.begin() as connection:
                await connection.execute(text("DROP SCHEMA public CASCADE"))
                await connection.execute(text("CREATE SCHEMA public"))
                await connection.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()

    asyncio.run(reset())
    yield


@pytest.fixture(scope="session")
def worker():
    if not services_configured():
        yield None
        return

    log = INTEGRATION_DIR / ".worker.log"
    handle = log.open("w", encoding="utf-8")

    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "taskiq", "worker", "src.worker.main:broker", "--workers", "1"],
        env=os.environ.copy(),
        stdout=handle,
        stderr=subprocess.STDOUT,
    )

    def output() -> str:
        handle.flush()
        return log.read_text(encoding="utf-8")

    deadline = time.monotonic() + 60
    while "Listening started" not in output():
        if process.poll() is not None:
            raise RuntimeError(f"taskiq worker exited with {process.returncode}:\n{output()}")
        if time.monotonic() > deadline:
            process.kill()
            raise RuntimeError(f"taskiq worker never became ready:\n{output()}")
        time.sleep(0.2)

    try:
        yield process
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
        handle.close()


@pytest.fixture(autouse=True)
async def dispose_shared_engine():
    """Production code opens sessions from the module-level engine. Each test gets
    its own event loop, so pooled connections must not survive between them."""
    yield
    from src.core.database.sqlalchemy.core import engine

    await engine.dispose()


@pytest.fixture
async def db_session():
    engine = build_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def cache():
    from src.core.cache.redis.adapter import RedisCacheStore

    store = RedisCacheStore(settings.REDIS_URL)
    yield store
    await store.close_connection()


@pytest.fixture
async def task_broker(worker):
    from src.core.tasks.broker import broker

    await broker.startup()
    yield broker
    await broker.shutdown()

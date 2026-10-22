"""The app migrates its database on start: from nothing to head, once, however many
processes start at the same time."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from src.core.database import migrations
from src.core.settings.shared import settings


@pytest.fixture(autouse=True)
def captured(monkeypatch):
    # it prints itself and stops there in the app; here it goes on to pytest's capture too
    monkeypatch.setattr(migrations.logger, "propagate", True)


@pytest.fixture
async def empty_database():
    """A database of its own, created empty and dropped after: the suite's shared one is
    built from the models, not by migrating."""
    name = f"the_way_migrate_{uuid4().hex[:8]}_test"
    admin_url = make_url(settings.DATABASE_URL).set(database="postgres")
    admin = create_async_engine(admin_url, poolclass=pool.NullPool, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(settings.DATABASE_URL).set(database=name).render_as_string(hide_password=False)
    finally:
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


async def revision_of(url: str) -> str | None:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            return await connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        await engine.dispose()


def head() -> str:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(migrations._config()).get_current_head()


async def test_an_empty_database_is_brought_to_head(empty_database):
    await migrations.upgrade_to_head(empty_database)

    assert await revision_of(empty_database) == head()


async def test_processes_starting_together_migrate_once_and_all_start(empty_database, caplog):
    caplog.set_level("INFO", logger=migrations.__name__)

    await asyncio.gather(*(migrations.upgrade_to_head(empty_database) for _ in range(3)))

    assert await revision_of(empty_database) == head()
    said = [record.getMessage() for record in caplog.records if record.name == migrations.__name__]
    assert sum(message.startswith("Database migrated from None") for message in said) == 1
    assert sum(message.startswith("Database already at") for message in said) == 2


async def test_a_database_at_head_is_left_alone(empty_database, caplog):
    await migrations.upgrade_to_head(empty_database)
    caplog.set_level("INFO", logger=migrations.__name__)

    await migrations.upgrade_to_head(empty_database)

    assert any(record.getMessage() == f"Database already at {head()}; no migrations to run" for record in caplog.records)

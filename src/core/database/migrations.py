"""Brings the database up to the code's schema when the app starts.

Every process that runs the app's lifespan -- each API replica and the worker
(taskiq_fastapi runs it too) -- calls this on start. A Postgres advisory lock lets one of
them migrate at a time: the others wait, then find the database already at head and do
nothing. A migration that fails stops the process from starting, rather than letting new
code run against an old schema.
"""

import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger(__name__)
# Printed whatever the process's logging: under uvicorn only its own loggers show INFO, and
# the worker has no uvicorn at all -- and whether a deploy migrated is the one line worth
# finding in the logs. In uvicorn's format, so it reads as part of the same start-up.
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

BACKEND_ROOT = Path(__file__).resolve().parents[3]

# Any fixed number, the same in every process: it names the lock, nothing else.
LOCK_KEY = 7_211_093_457


def _config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    return config


def _upgrade(connection: Connection, config: Config) -> tuple[str | None, str | None]:
    """Runs on the locked connection; returns the revision before and after."""
    before = MigrationContext.configure(connection).get_current_revision()
    head = ScriptDirectory.from_config(config).get_current_head()
    if before == head:
        return before, head
    # env.py runs the migrations on this connection, and leaves the app's logging alone
    config.attributes["connection"] = connection
    command.upgrade(config, "head")
    return before, MigrationContext.configure(connection).get_current_revision()


async def upgrade_to_head(database_url: str, lock_timeout_seconds: int = 300) -> None:
    config = _config()
    engine = create_async_engine(database_url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            # a session-level lock, held until this connection closes: another process
            # starting now waits here instead of migrating alongside
            await asyncio.wait_for(
                connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": LOCK_KEY}),
                timeout=lock_timeout_seconds,
            )
            await connection.commit()
            try:
                before, after = await connection.run_sync(_upgrade, config)
                await connection.commit()
            finally:
                await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                await connection.commit()
    finally:
        await engine.dispose()

    if before == after:
        logger.info("Database already at %s; no migrations to run", after)
    else:
        logger.info("Database migrated from %s to %s", before, after)

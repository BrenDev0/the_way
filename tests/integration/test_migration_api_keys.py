"""The migration that moved provider keys from users to organizations, on a database that has
real per-user keys: one per provider per organization survives (the owner's first), and going
back gives every organization's key to a person again."""

from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from src.core.database import migrations
from src.core.settings.shared import settings

BEFORE = "a1d4e7c92b30"
AFTER = "b2e5f8a3c016"


@pytest.fixture
async def database():
    """A database of its own, dropped after."""
    name = f"the_way_keys_{uuid4().hex[:8]}_test"
    admin = create_async_engine(
        make_url(settings.DATABASE_URL).set(database="postgres"), poolclass=pool.NullPool, isolation_level="AUTOCOMMIT"
    )
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(settings.DATABASE_URL).set(database=name).render_as_string(hide_password=False)
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


async def migrate(engine, direction, revision):
    config = migrations._config()

    def run(connection):
        config.attributes["connection"] = connection
        getattr(command, direction)(config, revision)

    async with engine.connect() as connection:
        await connection.run_sync(run)
        await connection.commit()


async def seed_organization(connection, roles_and_keys):
    """An organization whose people each hold keys; returns {role: user id} and the org id."""
    organization = uuid4()
    await connection.execute(
        text("INSERT INTO organizations (id, name) VALUES (:id, 'Acme')"), {"id": organization}
    )
    users = {}
    for role, keys in roles_and_keys.items():
        user = uuid4()
        users[role] = user
        await connection.execute(
            text(
                "INSERT INTO users (id, organization_id, email, email_hash, password, role) "
                "VALUES (:id, :org, 'e', :hash, 'p', :role)"
            ),
            {"id": user, "org": organization, "hash": f"h-{user}", "role": role},
        )
        for provider, last_four in keys:
            await connection.execute(
                text(
                    "INSERT INTO api_keys (id, organization_id, user_id, provider, secret, last_four) "
                    "VALUES (:id, :org, :user, :provider, :secret, :last_four)"
                ),
                {"id": uuid4(), "org": organization, "user": user, "provider": provider, "secret": f"enc::{last_four}", "last_four": last_four},
            )
    return organization, users


async def test_one_key_per_provider_survives_and_the_owners_wins(database):
    await migrate(database, "upgrade", BEFORE)
    async with database.connect() as connection:
        organization, _ = await seed_organization(
            connection,
            {
                "member": [("anthropic", "memb"), ("openai", "oai1")],
                "owner": [("anthropic", "ownr")],
                "admin": [("anthropic", "admn"), ("gohighlevel", "ghl1")],
            },
        )
        await connection.commit()

    await migrate(database, "upgrade", AFTER)

    async with database.connect() as connection:
        rows = (
            await connection.execute(
                text("SELECT provider, last_four FROM api_keys WHERE organization_id = :org ORDER BY provider"),
                {"org": organization},
            )
        ).all()
        columns = {
            row[0]
            for row in await connection.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'api_keys'")
            )
        }

    assert [tuple(row) for row in rows] == [
        ("anthropic", "ownr"),  # three people held one; the owner's is kept
        ("gohighlevel", "ghl1"),
        ("openai", "oai1"),
    ]
    assert "user_id" not in columns
    assert "issued_by" not in columns
    assert "set_by" in columns


async def test_without_an_owner_the_most_recently_set_key_is_kept(database):
    await migrate(database, "upgrade", BEFORE)
    async with database.connect() as connection:
        organization, users = await seed_organization(
            connection, {"admin": [("openai", "old1")], "member": [("openai", "new2")]}
        )
        await connection.execute(
            text("UPDATE api_keys SET updated_at = now() + interval '1 hour' WHERE user_id = :user"),
            {"user": users["member"]},
        )
        await connection.commit()

    await migrate(database, "upgrade", AFTER)

    async with database.connect() as connection:
        kept = (await connection.execute(text("SELECT last_four FROM api_keys WHERE organization_id = :org"), {"org": organization})).scalar_one()
    assert kept == "new2"


async def test_going_back_gives_each_organizations_keys_to_its_owner(database):
    await migrate(database, "upgrade", BEFORE)
    async with database.connect() as connection:
        organization, users = await seed_organization(
            connection, {"member": [("anthropic", "memb")], "owner": [("openai", "oai1")]}
        )
        await connection.commit()
    await migrate(database, "upgrade", AFTER)

    await migrate(database, "downgrade", BEFORE)

    async with database.connect() as connection:
        rows = (
            await connection.execute(
                text("SELECT provider, user_id FROM api_keys WHERE organization_id = :org ORDER BY provider"),
                {"org": organization},
            )
        ).all()
    assert [(provider, user) for provider, user in rows] == [("anthropic", users["owner"]), ("openai", users["owner"])]


async def test_the_old_shape_can_be_reached_again_and_left_once_more(database):
    await migrate(database, "upgrade", AFTER)
    await migrate(database, "downgrade", BEFORE)
    await migrate(database, "upgrade", AFTER)

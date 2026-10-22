from .base import AppSettings


class MigrateSettings(AppSettings):
    """What `alembic upgrade head` reads: the database, and nothing else. The migrate
    service is given no other secret, and needs none."""

    DATABASE_URL: str


settings = MigrateSettings()

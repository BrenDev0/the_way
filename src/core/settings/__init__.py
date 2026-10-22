"""Settings, one module per service in docker-compose.yml.

    shared    what the api and the worker both need  (compose: the shared environment)
    api       what only the api reads                (compose: api)
    worker    what only the worker reads             (compose: worker)
    migrate   what `alembic upgrade head` reads      (compose: migrate)
    render    what the render service reads          (compose: render)

Import the module of the service you are in, and nothing else is loaded: a process that
imports `migrate` needs only DATABASE_URL, and `render` needs no database, no Redis and none
of the app's secrets. Each module is a class plus one instance, `settings`; import it as
`from src.core.settings.api import settings as api_settings`, and the shared one as plain
`settings`.

All of them read the same environment and the same .env, and ignore the variables they do
not declare. A variable is named exactly what the deployment sets, whichever module holds it.
Nothing is imported here on purpose: importing the package must not load any of them.
"""

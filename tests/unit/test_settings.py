"""Settings are split by service, as docker-compose.yml is: shared (api and worker), api,
worker, migrate and render. The deployment sets one flat environment per service, so a
variable's name is a contract with it. These tests keep the split from changing that, and
prove that a service loads only what it needs."""

import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Every settings module, with the compose service(s) that load it.
MODULES = {
    "src.core.settings.shared": "api + worker",
    "src.core.settings.api": "api (the worker loads it too, because it runs the api's app)",
    "src.core.settings.worker": "worker (the api loads it too, to build the same broker)",
    "src.core.settings.migrate": "migrate",
    "src.core.settings.render": "render",
}

# Every variable a service may be given, as it is named today. Adding one is a decision:
# add it here, in the module of the service that reads it. Removing or renaming one breaks
# a deployment.
VARIABLES = {
    # shared
    "DATABASE_URL", "DATABASE_POOL_SIZE", "DATABASE_MAX_OVERFLOW", "DATABASE_MIGRATE_ON_STARTUP",
    "REDIS_URL", "TASKIQ_BROKER_URL", "TASKIQ_RESULT_BACKEND_URL", "TASKIQ_RESULT_TTL_SECONDS",
    "TASKIQ_STREAM_NAME", "TASKIQ_CONSUMER_GROUP", "CRYPTOGRAPHY_FERNET_KEY", "REQUEST_SIGNING_SECRET",
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
    "BUCKET_NAME", "BUCKET_PREFIX", "BUCKET_ENDPOINT", "BUCKET_PUBLIC_ENDPOINT", "BUCKET_REGION",
    "BUCKET_ACCESS_KEY_ID", "BUCKET_SECRET_ACCESS_KEY",
    "PUBLIC_API_URL", "FILE_LINK_SECRET", "RENDER_URL", "RENDER_SHARED_SECRET",
    # api
    "CORS_ALLOWED_ORIGINS", "REQUEST_SIGNATURE_WINDOW_SECONDS",
    "RATE_LIMIT_MAX_REQUESTS", "RATE_LIMIT_WINDOW_SECONDS", "RATE_LIMIT_BLOCK_SECONDS",
    "PUBLIC_PROXY_HOPS", "WEB_PROXY_HOPS",
    "SESSION_COOKIE_NAME", "SESSION_COOKIE_SECURE", "SESSION_COOKIE_SAMESITE", "SESSION_TTL_SECONDS",
    "DESKTOP_SESSION_TTL_SECONDS", "DESKTOP_LOGIN_WINDOW_SECONDS",
    "DESKTOP_LOGIN_MAX_FAILURES_PER_EMAIL", "DESKTOP_LOGIN_MAX_FAILURES_PER_IP",
    "INVITATION_ACCEPT_URL", "OWNER_INVITATION_ACCEPT_URL", "DESKTOP_DOWNLOAD_PAGE_URL",
    # worker
    "TASKIQ_XREAD_BLOCK_MS", "TASKIQ_SOCKET_TIMEOUT_SECONDS", "TASKIQ_IDLE_TIMEOUT_SECONDS",
    "TASKIQ_HEARTBEAT_SECONDS", "TASKIQ_HEARTBEAT_MAX_SECONDS",
    # render
    "RENDER_TIMEOUT_SECONDS", "RENDER_MAX_CONCURRENT", "RENDER_RESTART_AFTER",
}


def fields(module: str):
    return type(import_module(module).settings).model_fields


def declared() -> dict[str, list[str]]:
    """Variable -> the modules that declare it."""
    owners: dict[str, list[str]] = {}
    for module in MODULES:
        for name in fields(module):
            owners.setdefault(name, []).append(module)
    return owners


def required(module: str) -> set[str]:
    return {name for name, field in fields(module).items() if field.is_required()}


def run_clean(code: str, env: dict[str, str], tmp_path: Path) -> subprocess.CompletedProcess:
    """Run `code` in a fresh interpreter whose whole environment is `env` and which sits in an
    empty directory, so no .env and nothing inherited can feed the settings."""
    return subprocess.run(
        [sys.executable, "-c", code],
        env={"PYTHONPATH": str(ROOT), **env},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )


APP = ("src.core.settings.shared", "src.core.settings.api", "src.core.settings.worker")


def test_no_variable_is_declared_twice_among_the_modules_one_process_loads():
    """The api and the worker each load shared, api and worker together: a variable declared
    in two of them would have two owners in one process."""
    twice = {
        name: [m for m in modules if m in APP]
        for name, modules in declared().items()
        if len([m for m in modules if m in APP]) > 1
    }

    assert twice == {}


def test_only_two_names_are_read_by_more_than_one_service():
    """DATABASE_URL: the app and the migrate service. RENDER_SHARED_SECRET: the callers send
    it and the render service checks it, so it has to be the same value on both."""
    across = {name: set(modules) for name, modules in declared().items() if len(modules) > 1}

    assert across == {
        "DATABASE_URL": {"src.core.settings.shared", "src.core.settings.migrate"},
        "RENDER_SHARED_SECRET": {"src.core.settings.shared", "src.core.settings.render"},
    }


def test_the_split_keeps_every_variable_the_deployment_sets_and_adds_none_unannounced():
    assert set(declared()) == VARIABLES


def test_what_each_service_must_be_given():
    assert required("src.core.settings.shared") == {
        "DATABASE_URL",
        "REDIS_URL",
        "TASKIQ_BROKER_URL",
        "CRYPTOGRAPHY_FERNET_KEY",
        "REQUEST_SIGNING_SECRET",
    }
    assert required("src.core.settings.migrate") == {"DATABASE_URL"}
    # the rest start on defaults: the worker loads the api's and the api the worker's
    assert required("src.core.settings.api") == set()
    assert required("src.core.settings.worker") == set()
    assert required("src.core.settings.render") == set()


def test_migrate_starts_with_only_the_database_url(tmp_path):
    result = run_clean(
        "import sys; import src.core.settings.migrate as m; "
        "assert m.settings.DATABASE_URL == 'postgresql+asyncpg://u:p@db/x'; "
        "assert 'src.core.settings.shared' not in sys.modules",
        {"DATABASE_URL": "postgresql+asyncpg://u:p@db/x"},
        tmp_path,
    )

    assert result.returncode == 0, result.stderr


def test_migrate_refuses_to_start_without_the_database_url(tmp_path):
    result = run_clean("import src.core.settings.migrate", {}, tmp_path)

    assert result.returncode != 0
    assert "DATABASE_URL" in result.stderr


def test_render_starts_with_an_empty_environment_and_loads_none_of_the_apps(tmp_path):
    """The render service is given none of the app's secrets. Its config module imports, with
    nothing set, without touching the shared, api or worker settings."""
    result = run_clean(
        "import sys; import src.render.config as c; "
        "assert c.SHARED_SECRET == '' and c.MAX_CONCURRENT == 2 and c.RESTART_AFTER == 100; "
        "assert c.RENDER_TIMEOUT_SECONDS == 30; "
        "loaded = [m for m in ('shared', 'api', 'worker') if f'src.core.settings.{m}' in sys.modules]; "
        "assert not loaded, loaded",
        {},
        tmp_path,
    )

    assert result.returncode == 0, result.stderr


def test_render_reads_its_limits_from_its_environment(tmp_path):
    result = run_clean(
        "import src.render.config as c; "
        "assert (c.SHARED_SECRET, c.MAX_CONCURRENT, c.RESTART_AFTER, c.RENDER_TIMEOUT_SECONDS) == ('s3cret', 5, 7, 12.5)",
        {
            "RENDER_SHARED_SECRET": "s3cret",
            "RENDER_MAX_CONCURRENT": "5",
            "RENDER_RESTART_AFTER": "7",
            "RENDER_TIMEOUT_SECONDS": "12.5",
        },
        tmp_path,
    )

    assert result.returncode == 0, result.stderr


def test_the_api_and_the_worker_start_with_only_what_they_must_be_given(tmp_path):
    """Everything outside the required five has a default, in every module the two load."""
    result = run_clean(
        "import src.core.settings.shared, src.core.settings.api, src.core.settings.worker",
        {
            "DATABASE_URL": "postgresql+asyncpg://u:p@db/x",
            "REDIS_URL": "redis://r:6379/0",
            "TASKIQ_BROKER_URL": "memory://",
            "CRYPTOGRAPHY_FERNET_KEY": "k",
            "REQUEST_SIGNING_SECRET": "s",
        },
        tmp_path,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("missing", sorted(required("src.core.settings.shared")))
def test_the_app_refuses_to_start_without_each_required_variable(tmp_path, missing):
    env = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@db/x",
        "REDIS_URL": "redis://r:6379/0",
        "TASKIQ_BROKER_URL": "memory://",
        "CRYPTOGRAPHY_FERNET_KEY": "k",
        "REQUEST_SIGNING_SECRET": "s",
    }
    del env[missing]

    result = run_clean("import src.core.settings.shared", env, tmp_path)

    assert result.returncode != 0
    assert missing in result.stderr


def test_a_service_reads_its_variables_from_the_flat_environment(monkeypatch):
    from src.core.settings.api import ApiSettings
    from src.core.settings.worker import WorkerSettings

    monkeypatch.setenv("INVITATION_ACCEPT_URL", "https://panel.example/accept")
    monkeypatch.setenv("TASKIQ_HEARTBEAT_SECONDS", "15")

    assert ApiSettings().INVITATION_ACCEPT_URL == "https://panel.example/accept"
    assert WorkerSettings().TASKIQ_HEARTBEAT_SECONDS == 15


def test_a_service_ignores_variables_that_belong_to_another():
    from src.core.settings.api import ApiSettings

    assert not hasattr(ApiSettings(), "DATABASE_URL")

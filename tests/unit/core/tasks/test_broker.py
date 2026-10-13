import pytest
import taskiq_fastapi
from taskiq import InMemoryBroker
from taskiq_redis import RedisStreamBroker

from src.core.settings import settings
from src.core.tasks.broker import HeartbeatStreamBroker, broker, build_broker
from src.worker import health

in_memory_only = pytest.mark.skipif(
    settings.TASKIQ_BROKER_URL != "memory://",
    reason="needs the in-memory broker; the environment points at a real one",
)


@in_memory_only
def test_memory_url_builds_an_in_memory_broker():
    assert isinstance(broker, InMemoryBroker)


def test_redis_url_builds_a_stream_broker(monkeypatch):
    monkeypatch.setattr(settings, "TASKIQ_BROKER_URL", "redis://localhost:6379/1")

    built = build_broker()

    assert isinstance(built, RedisStreamBroker)
    assert built.result_backend is not None
    assert built.queue_name == settings.TASKIQ_STREAM_NAME
    assert built.consumer_group_name == settings.TASKIQ_CONSUMER_GROUP


def test_the_stream_broker_renews_what_it_runs_and_reads_one_at_a_time(monkeypatch):
    monkeypatch.setattr(settings, "TASKIQ_BROKER_URL", "redis://localhost:6379/1")

    built = build_broker()

    # behaviour proved against a real Redis in tests/integration/test_broker.py
    assert isinstance(built, HeartbeatStreamBroker)
    assert built.count == 1
    assert built.idle_timeout == settings.TASKIQ_IDLE_TIMEOUT_SECONDS * 1000
    assert built.heartbeat < settings.TASKIQ_IDLE_TIMEOUT_SECONDS  # renewed well inside the timeout


def test_a_new_consumer_group_drains_the_backlog(monkeypatch):
    monkeypatch.setattr(settings, "TASKIQ_BROKER_URL", "redis://localhost:6379/1")

    assert build_broker().consumer_id == "0"


def test_result_backend_url_falls_back_to_the_broker_url(monkeypatch):
    monkeypatch.setattr(settings, "TASKIQ_BROKER_URL", "redis://localhost:6379/1")
    monkeypatch.setattr(settings, "TASKIQ_RESULT_BACKEND_URL", None)

    assert settings.taskiq_result_backend_url() == "redis://localhost:6379/1"


def test_result_backend_url_is_used_when_set(monkeypatch):
    monkeypatch.setattr(settings, "TASKIQ_RESULT_BACKEND_URL", "redis://elsewhere:6379/2")

    assert settings.taskiq_result_backend_url() == "redis://elsewhere:6379/2"


def test_tasks_are_registered_on_the_broker():
    registered = set(broker.get_all_tasks())

    assert "src.worker.health:ping" in registered
    assert "src.worker.health:check_dependencies" in registered


@in_memory_only
async def test_a_task_round_trips_through_the_broker():
    await broker.startup()
    try:
        task = await health.ping.kiq()
        result = await task.wait_result(timeout=5)
    finally:
        await broker.shutdown()

    assert not result.is_err
    assert result.return_value


@in_memory_only
async def test_dependency_injection_reaches_a_task(cache_store):
    from src.worker import dependencies as worker_dependencies

    broker.add_dependency_context({})
    broker.dependency_overrides[worker_dependencies.get_cache_store] = lambda: cache_store

    await broker.startup()
    try:
        task = await health.check_dependencies.kiq()
        result = await task.wait_result(timeout=5)
    finally:
        await broker.shutdown()
        broker.dependency_overrides.pop(worker_dependencies.get_cache_store, None)

    assert not result.is_err
    assert result.return_value is True
    assert health.PROBE_KEY in cache_store.data


def test_fastapi_bridge_registers_worker_lifecycle_handlers():
    probe = InMemoryBroker()
    taskiq_fastapi.init(probe, "src.api.main:app")

    from taskiq import TaskiqEvents

    assert probe.event_handlers[TaskiqEvents.WORKER_STARTUP]
    assert probe.event_handlers[TaskiqEvents.WORKER_SHUTDOWN]


@pytest.mark.parametrize("attribute", ["TASKIQ_STREAM_NAME", "TASKIQ_CONSUMER_GROUP"])
def test_stream_settings_are_configured(attribute):
    assert getattr(settings, attribute)

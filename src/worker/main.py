import taskiq_fastapi

from src.core.tasks.broker import broker

from . import health as health_tasks

TASK_MODULES = (health_tasks,)

taskiq_fastapi.init(broker, "src.api.main:app")

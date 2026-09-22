import taskiq_fastapi

from src.conversations import tasks as conversation_tasks
from src.core.tasks.broker import broker

from . import health as health_tasks

TASK_MODULES = (health_tasks, conversation_tasks)

taskiq_fastapi.init(broker, "src.api.main:app")

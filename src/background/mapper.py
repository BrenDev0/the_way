from collections.abc import Sequence

from src.conversations import mapper as conversations_mapper
from src.core.tools.domain import ClientRequest

from .domain import BackgroundTask
from .schemas import BackgroundTaskResponse


def domain_to_task_response(
    task: BackgroundTask, pending_approval: Sequence[ClientRequest] = ()
) -> BackgroundTaskResponse:
    return BackgroundTaskResponse(
        id=task.id,
        conversation_id=task.conversation_id,
        description=task.description,
        status=task.status,
        result=task.result,
        deliver_project=task.deliver_project,
        deliver_path=task.deliver_path,
        created_at=task.created_at,
        updated_at=task.updated_at,
        pending_approval=[conversations_mapper.request_to_response(r) for r in pending_approval],
    )

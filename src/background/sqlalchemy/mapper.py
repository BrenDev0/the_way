import re
import uuid

from src.background.domain import BackgroundTask, BackgroundTaskCreate, TaskStatus

from .models import BackgroundTaskRow


def folder_for(description: str, task_id: uuid.UUID) -> str:
    """Kebab-case folder name from the description, with the id's head so two similarly
    described tasks never write into the same folder."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", description.lower()).strip("-")[:40].rstrip("-")
    return f"{cleaned or 'task'}-{task_id.hex[:8]}"


def row_to_domain(row: BackgroundTaskRow) -> BackgroundTask:
    return BackgroundTask(
        id=row.id,
        organization_id=row.organization_id,
        user_id=row.user_id,
        conversation_id=row.conversation_id,
        description=row.description,
        instructions=row.instructions,
        folder=row.folder,
        deliver_project=row.deliver_project,
        deliver_path=row.deliver_path,
        status=TaskStatus(row.status),
        result=row.result,
        reported=row.reported,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def domain_create_to_row(task: BackgroundTaskCreate) -> BackgroundTaskRow:
    task_id = uuid.uuid4()
    return BackgroundTaskRow(
        id=task_id,
        organization_id=task.organization_id,
        user_id=task.user_id,
        conversation_id=task.conversation_id,
        description=task.description,
        instructions=task.instructions,
        folder=folder_for(task.description, task_id),
        deliver_project=task.deliver_project,
        deliver_path=task.deliver_path,
        status=TaskStatus.RUNNING,
        result=None,
        reported=False,
    )

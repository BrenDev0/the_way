from datetime import UTC, datetime
from uuid import uuid4

from src.background import mapper
from src.background.domain import BackgroundTask, TaskStatus


def test_a_task_delivered_to_a_project_root_can_be_listed():
    now = datetime.now(UTC)
    task = BackgroundTask(
        id=uuid4(), organization_id=uuid4(), user_id=uuid4(), conversation_id=None,
        description="Q", instructions="Write it", folder="q-1234",
        deliver_project="cx", deliver_path=".", status=TaskStatus.DONE, result="",
        reported=False, created_at=now, updated_at=now,
    )

    response = mapper.domain_to_task_response(task)

    assert response.deliver_path == "."
    assert response.description == "Q"

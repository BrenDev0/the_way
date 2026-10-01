from datetime import UTC, datetime
from uuid import uuid4

from src.background import use_cases as background_use_cases
from src.background.domain import BackgroundTask, TaskStatus


def task(project: str | None, path: str | None = None) -> BackgroundTask:
    now = datetime.now(UTC)
    return BackgroundTask(
        id=uuid4(), organization_id=uuid4(), user_id=uuid4(), conversation_id=None,
        description="Informe de ventas", instructions="...", folder="informe-de-ventas-1a2b3c4d",
        deliver_project=project, deliver_path=path, status=TaskStatus.RUNNING, result=None,
        reported=False, created_at=now, updated_at=now,
    )


def test_drafts_get_a_folder_of_their_own_so_one_never_lands_on_another():
    assert background_use_cases.delivery_target(task("Borradores")) == ("Borradores", "informe-de-ventas-1a2b3c4d")


def test_a_folder_the_user_named_is_used_as_given():
    assert background_use_cases.delivery_target(task("Borradores", "ventas")) == ("Borradores", "ventas")
    assert background_use_cases.delivery_target(task("Clientes", "reportes")) == ("Clientes", "reportes")


def test_a_named_project_without_a_folder_gets_its_top_level():
    assert background_use_cases.delivery_target(task("Clientes")) == ("Clientes", ".")


def test_a_task_with_nowhere_to_go_is_not_delivered():
    assert background_use_cases.delivery_target(task(None)) is None

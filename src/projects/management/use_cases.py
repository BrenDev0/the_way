from collections.abc import Sequence
from uuid import UUID

from src.core.exceptions import NotFoundError
from src.projects.domain import Project
from src.projects.ports import (
    GetProjectFn,
    ListProjectsForOrganizationFn,
    UpdateProjectFn,
)
from src.users.ports import GetUserByIdFn


def _project_not_found() -> NotFoundError:
    return NotFoundError(message="Project not found", code="project_not_found")


async def resolve_organization_project(
    project_id: UUID, organization_id: UUID, get_project_fn: GetProjectFn
) -> Project:
    project = await get_project_fn(project_id, organization_id)
    if project is None:
        raise _project_not_found()
    return project


async def list_organization_projects(
    organization_id: UUID,
    list_projects_for_organization_fn: ListProjectsForOrganizationFn,
    owner_id: UUID | None = None,
) -> Sequence[Project]:
    return await list_projects_for_organization_fn(organization_id, owner_id)


async def transfer_project(
    project: Project,
    new_owner_id: UUID,
    get_user_by_id_fn: GetUserByIdFn,
    update_project_fn: UpdateProjectFn,
) -> Project:
    new_owner = await get_user_by_id_fn(new_owner_id)
    if new_owner is None or new_owner.organization_id != project.organization_id:
        raise NotFoundError(message="User not found", code="user_not_found")

    updated = await update_project_fn(project.id, {"owner_id": new_owner.id})
    if updated is None:
        raise _project_not_found()
    return updated

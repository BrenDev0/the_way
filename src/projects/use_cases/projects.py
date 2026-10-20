from collections.abc import Sequence
from uuid import UUID

from src.core.bucket.ports import BucketStore
from src.core.exceptions import AuthorizationError, ConflictError
from src.projects import config
from src.projects.domain import Project, ProjectCreate
from src.projects.ports import (
    CreateProjectFn,
    DeleteProjectFn,
    GetOrCreateLibraryFn,
    GetProjectFn,
    ListProjectFileIdsFn,
    ListProjectsForOwnerFn,
    UpdateProjectFn,
)
from src.users.domain import Role, User

from .common import delete_objects, project_not_found, validate_name


async def resolve_owned_project(
    project_id: UUID, user: User, get_project_fn: GetProjectFn
) -> Project:
    """A project of the user's own -- for renaming or deleting it. The library is
    nobody's, so it can be neither."""
    project = await get_project_fn(project_id, user.organization_id)
    if project is None or project.owner_id != user.id:
        raise project_not_found()
    return project


LIBRARY_EDITORS = frozenset({Role.OWNER, Role.ADMIN})


async def resolve_readable_project(
    project_id: UUID, user: User, get_project_fn: GetProjectFn
) -> Project:
    """The user's own project, or their organization's library, which every member
    reads."""
    project = await get_project_fn(project_id, user.organization_id)
    if project is None or not (project.owner_id == user.id or project.shared):
        raise project_not_found()
    return project


async def resolve_writable_project(
    project_id: UUID, user: User, get_project_fn: GetProjectFn
) -> Project:
    """Where the user may add, change or remove files and folders: their own projects,
    and the library when they are an owner or admin."""
    project = await resolve_readable_project(project_id, user, get_project_fn)
    if project.shared and user.role not in LIBRARY_EDITORS:
        raise AuthorizationError(
            message="Only owners and admins can change the organization's library",
            code="library_read_only",
        )
    return project


def _not_reserved(name: str) -> str:
    if name.lower() == config.LIBRARY_PROJECT.lower():
        raise ConflictError(
            message=f"'{config.LIBRARY_PROJECT}' is the organization's shared library; pick another name",
            code="project_name_reserved",
        )
    return name


async def create_project(
    owner: User,
    name: str,
    list_projects_for_owner_fn: ListProjectsForOwnerFn,
    create_project_fn: CreateProjectFn,
) -> Project:
    cleaned = _not_reserved(validate_name(name))

    held = await list_projects_for_owner_fn(owner.id)
    if any(project.name.lower() == cleaned.lower() for project in held):
        raise ConflictError(
            message="A project with that name already exists",
            code="project_name_taken",
        )

    return await create_project_fn(
        ProjectCreate(organization_id=owner.organization_id, owner_id=owner.id, name=cleaned)
    )


async def list_projects(
    owner_id: UUID, list_projects_for_owner_fn: ListProjectsForOwnerFn
) -> Sequence[Project]:
    return await list_projects_for_owner_fn(owner_id)


async def rename_project(
    project: Project, name: str, update_project_fn: UpdateProjectFn
) -> Project:
    updated = await update_project_fn(project.id, {"name": _not_reserved(validate_name(name))})
    if updated is None:
        raise project_not_found()
    return updated


async def delete_project(
    project: Project,
    list_project_file_ids_fn: ListProjectFileIdsFn,
    delete_project_fn: DeleteProjectFn,
    bucket_store: BucketStore,
) -> None:
    file_ids = await list_project_file_ids_fn(project.id)

    if not await delete_project_fn(project.id):
        raise project_not_found()

    await delete_objects(project.organization_id, file_ids, bucket_store)


async def get_library(
    organization_id: UUID, get_or_create_library_fn: GetOrCreateLibraryFn
) -> Project:
    """The organization's library -- brand folders of logos, images and brand books --
    made the first time anyone asks for it."""
    return await get_or_create_library_fn(organization_id, config.LIBRARY_PROJECT)

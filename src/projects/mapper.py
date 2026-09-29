from .domain import Folder, Project, ProjectContents, ProjectFile
from .schemas import (
    FileResponse,
    FolderResponse,
    ProjectContentsResponse,
    ProjectResponse,
)


def domain_to_project_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        owner_id=project.owner_id,
        name=project.name,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def domain_to_folder_response(folder: Folder) -> FolderResponse:
    return FolderResponse(
        id=folder.id,
        project_id=folder.project_id,
        parent_id=folder.parent_id,
        name=folder.name,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


def domain_to_file_response(project_file: ProjectFile) -> FileResponse:
    return FileResponse(
        id=project_file.id,
        project_id=project_file.project_id,
        folder_id=project_file.folder_id,
        name=project_file.name,
        content_type=project_file.content_type,
        size_bytes=project_file.size_bytes,
        status=project_file.status,
        uploaded_by=project_file.uploaded_by,
        created_at=project_file.created_at,
        updated_at=project_file.updated_at,
    )


def domain_to_contents_response(contents: ProjectContents) -> ProjectContentsResponse:
    return ProjectContentsResponse(
        folders=[domain_to_folder_response(folder) for folder in contents.folders],
        files=[domain_to_file_response(project_file) for project_file in contents.files],
    )

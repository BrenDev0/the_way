from src.projects.domain import (
    FileStatus,
    Folder,
    FolderCreate,
    Project,
    ProjectCreate,
    ProjectFile,
    ProjectFileCreate,
)

from .models import FileRow, FolderRow, ProjectRow


def project_row_to_domain(row: ProjectRow) -> Project:
    return Project(
        id=row.id,
        organization_id=row.organization_id,
        owner_id=row.owner_id,
        name=row.name,
        created_at=row.created_at,
        updated_at=row.updated_at,
        shared=row.shared,
    )


def project_create_to_row(project: ProjectCreate) -> ProjectRow:
    return ProjectRow(
        organization_id=project.organization_id,
        owner_id=project.owner_id,
        name=project.name,
    )


def folder_row_to_domain(row: FolderRow) -> Folder:
    return Folder(
        id=row.id,
        project_id=row.project_id,
        parent_id=row.parent_id,
        name=row.name,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def folder_create_to_row(folder: FolderCreate) -> FolderRow:
    return FolderRow(
        project_id=folder.project_id,
        parent_id=folder.parent_id,
        name=folder.name,
    )


def file_row_to_domain(row: FileRow) -> ProjectFile:
    return ProjectFile(
        id=row.id,
        project_id=row.project_id,
        folder_id=row.folder_id,
        name=row.name,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        status=FileStatus(row.status),
        uploaded_by=row.uploaded_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def file_create_to_row(project_file: ProjectFileCreate) -> FileRow:
    return FileRow(
        project_id=project_file.project_id,
        folder_id=project_file.folder_id,
        name=project_file.name,
        content_type=project_file.content_type,
        size_bytes=project_file.size_bytes,
        status=FileStatus.PENDING,
        uploaded_by=project_file.uploaded_by,
    )

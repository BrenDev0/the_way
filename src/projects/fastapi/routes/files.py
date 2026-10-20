"""A project's files: uploading, reading, renaming, moving and deleting them."""

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Response, status

from src.projects import config
from src.projects.fastapi.dependencies import (
    Bucket,
    CreateFile,
    CurrentUser,
    DeleteFile,
    FindEntry,
    GetFile,
    GetFolder,
    ReadableProject,
    UpdateFile,
    WritableProject,
)
from src.projects.fastapi.schemas import (
    DeleteResponse,
    FileDownloadResponse,
    FileResponse,
    FileUploadTicketResponse,
    MoveFileRequest,
    RenameRequest,
    RequestFileUploadRequest,
)
from src.projects.use_cases import files as file_use_cases

router = APIRouter(tags=["projects"])


@router.post(
    "/{project_id}/files",
    response_model=FileUploadTicketResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_upload_route(
    payload: RequestFileUploadRequest,
    project: WritableProject,
    current_user: CurrentUser,
    bucket_store: Bucket,
    get_folder_fn: GetFolder,
    find_entry_fn: FindEntry,
    delete_file_fn: DeleteFile,
    create_file_fn: CreateFile,
) -> FileUploadTicketResponse:
    project_file, upload_url = await file_use_cases.request_upload(
        project=project,
        name=payload.name,
        folder_id=payload.folder_id,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        uploaded_by=current_user.id,
        get_folder_fn=get_folder_fn,
        find_entry_fn=find_entry_fn,
        delete_file_fn=delete_file_fn,
        create_file_fn=create_file_fn,
        bucket_store=bucket_store,
    )
    return FileUploadTicketResponse(
        file=FileResponse.from_domain(project_file),
        upload_url=upload_url,
        expires_in_seconds=config.UPLOAD_URL_TTL_SECONDS,
    )


@router.post("/{project_id}/files/{file_id}/complete", response_model=FileResponse)
async def complete_upload_route(
    file_id: UUID,
    project: WritableProject,
    bucket_store: Bucket,
    get_file_fn: GetFile,
    update_file_fn: UpdateFile,
) -> FileResponse:
    project_file = await file_use_cases.complete_upload(
        project=project,
        file_id=file_id,
        get_file_fn=get_file_fn,
        update_file_fn=update_file_fn,
        bucket_store=bucket_store,
    )
    return FileResponse.from_domain(project_file)


@router.get("/{project_id}/files/{file_id}/download", response_model=FileDownloadResponse)
async def request_download_route(
    file_id: UUID,
    project: ReadableProject,
    bucket_store: Bucket,
    get_file_fn: GetFile,
) -> FileDownloadResponse:
    project_file, download_url = await file_use_cases.request_download(
        project=project,
        file_id=file_id,
        get_file_fn=get_file_fn,
        bucket_store=bucket_store,
    )
    return FileDownloadResponse(
        file=FileResponse.from_domain(project_file),
        download_url=download_url,
        expires_in_seconds=config.DOWNLOAD_URL_TTL_SECONDS,
    )


@router.get("/{project_id}/files/{file_id}/content")
async def file_content_route(
    file_id: UUID,
    project: ReadableProject,
    bucket_store: Bucket,
    get_file_fn: GetFile,
) -> Response:
    """The file itself, with its own content type -- for opening it in the app or saving it,
    from wherever the client is: the server fetches it from the bucket."""
    project_file, content = await file_use_cases.read_file(
        project=project, file_id=file_id, get_file_fn=get_file_fn, bucket_store=bucket_store
    )
    return Response(
        content=content,
        media_type=project_file.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(project_file.name)}",
            # it is opened inside the app; nothing it contains should run as a page of ours
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.patch("/{project_id}/files/{file_id}", response_model=FileResponse)
async def rename_file_route(
    file_id: UUID,
    payload: RenameRequest,
    project: WritableProject,
    get_file_fn: GetFile,
    find_entry_fn: FindEntry,
    update_file_fn: UpdateFile,
) -> FileResponse:
    project_file = await file_use_cases.rename_file(
        project=project,
        file_id=file_id,
        name=payload.name,
        get_file_fn=get_file_fn,
        find_entry_fn=find_entry_fn,
        update_file_fn=update_file_fn,
    )
    return FileResponse.from_domain(project_file)


@router.post("/{project_id}/files/{file_id}/move", response_model=FileResponse)
async def move_file_route(
    file_id: UUID,
    payload: MoveFileRequest,
    project: WritableProject,
    get_file_fn: GetFile,
    get_folder_fn: GetFolder,
    find_entry_fn: FindEntry,
    update_file_fn: UpdateFile,
) -> FileResponse:
    project_file = await file_use_cases.move_file(
        project=project,
        file_id=file_id,
        folder_id=payload.folder_id,
        get_file_fn=get_file_fn,
        get_folder_fn=get_folder_fn,
        find_entry_fn=find_entry_fn,
        update_file_fn=update_file_fn,
    )
    return FileResponse.from_domain(project_file)


@router.delete("/{project_id}/files/{file_id}", response_model=DeleteResponse)
async def delete_file_route(
    file_id: UUID,
    project: WritableProject,
    bucket_store: Bucket,
    get_file_fn: GetFile,
    delete_file_fn: DeleteFile,
) -> DeleteResponse:
    await file_use_cases.delete_file(
        project=project,
        file_id=file_id,
        get_file_fn=get_file_fn,
        delete_file_fn=delete_file_fn,
        bucket_store=bucket_store,
    )
    return DeleteResponse(detail="File deleted")

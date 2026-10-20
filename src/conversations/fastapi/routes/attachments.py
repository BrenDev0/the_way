
from fastapi import APIRouter, status

from src.conversations import config
from src.conversations.fastapi.dependencies import CurrentUser, Files
from src.conversations.fastapi.schemas import (
    AttachmentUploadRequest,
    AttachmentUploadResponse,
)
from src.core.exceptions import ValidationError
from src.projects import config as projects_config

router = APIRouter(tags=["conversations"])


@router.post(
    "/attachments",
    response_model=AttachmentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_attachment_route(
    payload: AttachmentUploadRequest,
    current_user: CurrentUser,
    files: Files,
) -> AttachmentUploadResponse:
    """A place for a file the user is attaching to a message: their drafts project, in
    adjuntos/. Upload to the returned URL, complete it, then send its id with the message."""
    if payload.size_bytes > config.MAX_ATTACHMENT_BYTES:
        raise ValidationError(
            message=f"Attachments are limited to {config.MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB",
            code="attachment_too_large",
        )
    project = await files.project(projects_config.DRAFTS_PROJECT)
    project_file, upload_url = await files.upload_ticket(
        project, config.ATTACHMENTS_FOLDER, payload.name, payload.content_type, payload.size_bytes
    )
    return AttachmentUploadResponse(
        file_id=project_file.id,
        project_id=project.id,
        project=project.name,
        path=f"{config.ATTACHMENTS_FOLDER}/{project_file.name}",
        upload_url=upload_url,
    )

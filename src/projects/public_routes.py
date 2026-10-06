"""The one project route that needs no login: an image, by its signed link (links.py).

Mounted beside the API rather than in it -- an <img> sends neither a session nor the
request signature the rest of the web API requires. The signature in the link is the
whole of the permission, so anything wrong with a link is the same 404: whether the file
exists is not told to someone who cannot prove they may see it.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api import dependencies as api_dependencies
from src.core.bucket.domain import BucketError
from src.core.bucket.ports import BucketStore
from src.core.database.sqlalchemy import dependencies as db_dependencies
from src.core.exceptions import NotFoundError, ServiceUnavailableError

from . import config, keys, links
from .domain import FileStatus
from .sqlalchemy import adapter

router = APIRouter(tags=["files"])


def _not_found() -> NotFoundError:
    return NotFoundError(message="Image not found", code="image_not_found")


@router.get(links.VIEW_PATH, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
async def view_image_route(
    file_id: UUID,
    session: Annotated[AsyncSession, Depends(db_dependencies.get_db_session)],
    bucket_store: Annotated[BucketStore, Depends(api_dependencies.get_bucket_store)],
    sig: Annotated[str, Query(max_length=64)] = "",
) -> RedirectResponse:
    """Redirects to the image, at a bucket URL signed fresh for this request."""
    if not links.verify(file_id, sig):
        raise _not_found()

    found = await adapter.get_file_with_project(session, file_id)
    if found is None:
        raise _not_found()
    project_file, project = found
    if project_file.status is not FileStatus.READY or not project_file.content_type.startswith("image/"):
        raise _not_found()

    try:
        url = await bucket_store.presign_get(
            keys.file_key(project.organization_id, project_file.id), config.IMAGE_URL_TTL_SECONDS
        )
    except BucketError as exc:
        raise ServiceUnavailableError("Images are unavailable right now", "image_unavailable") from exc

    return RedirectResponse(
        url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Cache-Control": f"private, max-age={config.IMAGE_REDIRECT_CACHE_SECONDS}"},
    )

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

from src.core.bucket.ports import BucketStore
from src.fastapi import dependencies as api_dependencies
from src.projects import config, links
from src.projects.fastapi.dependencies import GetFileWithProject
from src.projects.use_cases import files as file_use_cases

router = APIRouter(tags=["files"])


@router.get(links.VIEW_PATH, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
async def view_image_route(
    file_id: UUID,
    get_file_with_project_fn: GetFileWithProject,
    bucket_store: Annotated[BucketStore, Depends(api_dependencies.get_bucket_store)],
    sig: Annotated[str, Query(max_length=64)] = "",
) -> RedirectResponse:
    """Redirects to the image, at a bucket URL signed fresh for this request."""
    url = await file_use_cases.request_image_url(
        file_id=file_id,
        signature=sig,
        get_file_with_project_fn=get_file_with_project_fn,
        bucket_store=bucket_store,
    )
    return RedirectResponse(
        url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Cache-Control": f"private, max-age={config.IMAGE_REDIRECT_CACHE_SECONDS}"},
    )

"""What the public download page needs: which installers are published, and a link to one.

No session: the page is for people who do not have the app yet. The routes still sit
behind request signing with the rest of the API, so only the panel's server calls them --
a browser gets a signed bucket link, never the bucket.
"""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from src.core.bucket.domain import BucketError
from src.core.bucket.ports import BucketStore
from src.core.exceptions import NotFoundError, ServiceUnavailableError
from src.fastapi import dependencies as api_dependencies
from src.fastapi.schemas import ApiBaseModel

from .. import config, versions

logger = logging.getLogger(__name__)

router = APIRouter(tags=["downloads"])

Bucket = Annotated[BucketStore, Depends(api_dependencies.get_bucket_store)]


def _unavailable(exc: BucketError) -> ServiceUnavailableError:
    """The bucket could not be read: the page is told to try again, not given a 500, and the
    reason is logged."""
    logger.warning("The installers bucket could not be read: %s", exc)
    return ServiceUnavailableError(
        message="Las descargas no están disponibles en este momento. Inténtalo de nuevo en unos minutos.",
        code="downloads_unavailable",
    )


class InstallerResponse(ApiBaseModel):
    platform: str
    label: str
    filename: str
    available: bool
    version: str | None = None
    size_bytes: int | None = None
    updated_at: datetime | None = None


class InstallerLinkResponse(ApiBaseModel):
    url: str
    filename: str


@router.get("/desktop", response_model=list[InstallerResponse])
async def list_installers(bucket: Bucket) -> list[InstallerResponse]:
    try:
        published = {item.key: item for item in await bucket.list(config.folder())}
        recorded = await versions.published(bucket)
    except BucketError as exc:
        raise _unavailable(exc) from exc
    listed = []
    for installer in config.INSTALLERS.values():
        found = published.get(config.key(installer))
        listed.append(
            InstallerResponse(
                platform=installer.platform,
                label=installer.label,
                filename=installer.filename,
                available=found is not None,
                version=recorded.get(installer.platform) if found else None,
                size_bytes=found.size if found else None,
                updated_at=found.modified if found else None,
            )
        )
    return listed


@router.get("/desktop/{platform}", response_model=InstallerLinkResponse)
async def installer_link(platform: str, bucket: Bucket) -> InstallerLinkResponse:
    installer = config.INSTALLERS.get(platform)
    try:
        published = installer is not None and await bucket.exists(config.key(installer))
    except BucketError as exc:
        raise _unavailable(exc) from exc
    if installer is None or not published:
        raise NotFoundError(
            message="Ese instalador todavía no está publicado.", code="installer_not_published"
        )
    try:
        url = await bucket.presign_get(
            config.key(installer), config.LINK_SECONDS, download_name=installer.filename
        )
    except BucketError as exc:
        raise _unavailable(exc) from exc
    return InstallerLinkResponse(url=url, filename=installer.filename)

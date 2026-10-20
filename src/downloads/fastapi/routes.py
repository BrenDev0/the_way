"""What the public download page needs: which installers are published, and a link to one.

No session: the page is for people who do not have the app yet. The routes still sit
behind request signing with the rest of the API, so only the panel's server calls them --
a browser gets a signed bucket link, never the bucket.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from src.core.bucket.ports import BucketStore
from src.core.exceptions import NotFoundError
from src.fastapi import dependencies as api_dependencies
from src.fastapi.schemas import ApiBaseModel

from .. import config, versions

router = APIRouter(tags=["downloads"])

Bucket = Annotated[BucketStore, Depends(api_dependencies.get_bucket_store)]


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
    published = {item.key: item for item in await bucket.list(config.folder())}
    recorded = await versions.published(bucket)
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
    if installer is None or not await bucket.exists(config.key(installer)):
        raise NotFoundError(
            message="Ese instalador todavía no está publicado.", code="installer_not_published"
        )
    url = await bucket.presign_get(
        config.key(installer), config.LINK_SECONDS, download_name=installer.filename
    )
    return InstallerLinkResponse(url=url, filename=installer.filename)

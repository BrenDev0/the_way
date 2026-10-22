"""What the desktop app asks to know whether a newer version of itself is out.

Public, like the download page: an app whose session has expired should still hear about
an update. It says only version numbers and the page's address.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from src.core.bucket.domain import BucketError
from src.core.bucket.ports import BucketStore
from src.fastapi import dependencies as api_dependencies
from src.fastapi.schemas import ApiBaseModel

from .. import config, versions

logger = logging.getLogger(__name__)

router = APIRouter(tags=["downloads"])

Bucket = Annotated[BucketStore, Depends(api_dependencies.get_bucket_store)]


class AppVersionResponse(ApiBaseModel):
    # per platform ("windows", "mac"): the latest published version, or None
    latest: dict[str, str | None]
    download_page_url: str | None = None


@router.get("/version", response_model=AppVersionResponse)
async def app_version(bucket: Bucket) -> AppVersionResponse:
    # A convenience ("is there a newer installer?"), asked as the app starts: when the bucket
    # cannot be read it says nothing is known, rather than failing that check with a 500. The
    # reason is logged, so a misconfigured bucket is still seen.
    try:
        latest = await versions.published(bucket)
    except BucketError as exc:
        logger.warning("Could not read the published app versions: %s", exc)
        latest = {installer.platform: None for installer in config.INSTALLERS.values()}
    return AppVersionResponse(latest=latest, download_page_url=config.download_page_url())

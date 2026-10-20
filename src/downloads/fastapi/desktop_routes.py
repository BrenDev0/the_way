"""What the desktop app asks to know whether a newer version of itself is out.

Public, like the download page: an app whose session has expired should still hear about
an update. It says only version numbers and the page's address.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from src.core.bucket.ports import BucketStore
from src.fastapi import dependencies as api_dependencies
from src.fastapi.schemas import ApiBaseModel

from .. import config, versions

router = APIRouter(tags=["downloads"])

Bucket = Annotated[BucketStore, Depends(api_dependencies.get_bucket_store)]


class AppVersionResponse(ApiBaseModel):
    # per platform ("windows", "mac"): the latest published version, or None
    latest: dict[str, str | None]
    download_page_url: str | None = None


@router.get("/version", response_model=AppVersionResponse)
async def app_version(bucket: Bucket) -> AppVersionResponse:
    return AppVersionResponse(
        latest=await versions.published(bucket), download_page_url=config.download_page_url()
    )

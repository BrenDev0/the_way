"""Links to a project image that work anywhere -- in an <img> on a page opened in the app,
in a browser, or in a page downloaded and opened on its own.

An <img> cannot send a login, so the link carries its own permission: the file id and a
signature over it. It never expires, since the page holding it must keep working; what it
leads to does. Opening it redirects to a presigned bucket URL made fresh each time and
good for a quarter of an hour. Only images are served this way.
"""

import hashlib
import hmac
import re
from uuid import UUID

from src.auth import config as auth_config
from src.core.settings import settings

VIEW_PATH = "/files/{file_id}/view"

# What a link looks like, whichever address the API was reached at when it was written.
LINK = re.compile(
    r"(?:https?://[^\s\"'()<>]+)?" + re.escape(auth_config.WEB_API_PREFIX)
    + r"/files/(?P<id>[0-9a-fA-F-]{36})/view\?sig=(?P<sig>[0-9a-f]{32})"
)


def _secret() -> bytes:
    return (settings.FILE_LINK_SECRET or settings.REQUEST_SIGNING_SECRET).encode()


def sign(file_id: UUID) -> str:
    # what is signed says what it is for, so no other signature made with this secret
    # can stand in for one
    message = f"project-file-view:{file_id}".encode()
    return hmac.new(_secret(), message, hashlib.sha256).hexdigest()[:32]


def verify(file_id: UUID, signature: str) -> bool:
    return hmac.compare_digest(sign(file_id), signature or "")


def view_url(file_id: UUID) -> str | None:
    """The link for an image, or None when the API's public address is not configured."""
    if not settings.PUBLIC_API_URL:
        return None
    base = settings.PUBLIC_API_URL.rstrip("/")
    path = VIEW_PATH.format(file_id=file_id)
    return f"{base}{auth_config.WEB_API_PREFIX}{path}?sig={sign(file_id)}"


def parse(url: str) -> UUID | None:
    """The file a link is for, if it is one of ours and its signature holds."""
    match = LINK.fullmatch(url.strip())
    if not match:
        return None
    try:
        file_id = UUID(match["id"])
    except ValueError:
        return None
    return file_id if verify(file_id, match["sig"]) else None

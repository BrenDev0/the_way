"""The desktop app's installers, as the public download page offers them.

They sit in the private bucket like every other file and go out through a short signed
link, so the bucket needs no public part. One file per platform, at a fixed key: publishing
a new version replaces it, and the page always offers the latest.
"""

from dataclasses import dataclass
from urllib.parse import urlparse

from src.core.settings import settings


@dataclass(frozen=True)
class Installer:
    platform: str
    label: str
    # the name the browser saves it as
    filename: str


INSTALLERS = {
    "windows": Installer("windows", "Windows", "THE-WAY-Setup.exe"),
    "mac": Installer("mac", "macOS", "THE-WAY-mac.zip"),
}

# Long enough to start a slow download -- the link only has to be valid when it begins.
LINK_SECONDS = 10 * 60


def key(installer: Installer) -> str:
    return _key(installer.platform, installer.filename)


# Beside each installer: the version it is, written when it is published. The desktop app
# compares its own against it to tell the operator a newer one is out.
VERSION_FILE = "latest.json"


def version_key(installer: Installer) -> str:
    return _key(installer.platform, VERSION_FILE)


def _key(platform: str, name: str) -> str:
    prefix = (settings.BUCKET_PREFIX or "").strip("/")
    parts = [prefix, "downloads", "desktop", platform, name]
    return "/".join(part for part in parts if part)


def download_page_url() -> str | None:
    """The public download page the desktop app sends people to: set outright, or the
    panel's own address, which the invitation link already names."""
    if settings.DESKTOP_DOWNLOAD_PAGE_URL:
        return settings.DESKTOP_DOWNLOAD_PAGE_URL
    if settings.INVITATION_ACCEPT_URL:
        parsed = urlparse(settings.INVITATION_ACCEPT_URL)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}/download"
    return None


def folder() -> str:
    prefix = (settings.BUCKET_PREFIX or "").strip("/")
    return "/".join(part for part in [prefix, "downloads", "desktop"] if part) + "/"

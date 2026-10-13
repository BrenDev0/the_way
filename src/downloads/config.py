"""The desktop app's installers, as the public download page offers them.

They sit in the private bucket like every other file and go out through a short signed
link, so the bucket needs no public part. One file per platform, at a fixed key: publishing
a new version replaces it, and the page always offers the latest.
"""

from dataclasses import dataclass

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
    prefix = (settings.BUCKET_PREFIX or "").strip("/")
    parts = [prefix, "downloads", "desktop", installer.platform, installer.filename]
    return "/".join(part for part in parts if part)


def folder() -> str:
    prefix = (settings.BUCKET_PREFIX or "").strip("/")
    return "/".join(part for part in [prefix, "downloads", "desktop"] if part) + "/"

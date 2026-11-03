"""The desktop app's installers, as the public download page offers them.

They sit in the private bucket like every other file and go out through a short signed
link, so the bucket needs no public part. Each is stored under a name that carries its
version (THE-WAY-Setup-0.1.7.exe) -- the browser saves a download under its key's own name,
whatever the bucket does with a header -- and `latest.json` beside them says which is the
latest. A publish keeps the newest few versions, so one can be rolled back to, and removes
the rest. Installers published before that sit at a fixed name (THE-WAY-Setup.exe), which
is still served until the next publish replaces it.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlparse

from src.core.settings.api import settings as api_settings
from src.core.settings.shared import settings


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

# Only a plain x.y.z goes into a file name: the version is read from a file in the bucket.
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def download_name(installer: Installer, version: str | None) -> str:
    """What the browser saves the installer as: the version in it when it is known
    (THE-WAY-Setup-0.1.7.exe), so two downloads are told apart and a file says what it is.
    The bucket still holds it at its one fixed name."""
    if not version or not _VERSION.match(version):
        return installer.filename
    path = PurePosixPath(installer.filename)
    return f"{path.stem}-{version}{path.suffix}"


# Long enough to start a slow download -- the link only has to be valid when it begins.
LINK_SECONDS = 10 * 60

# How many versions of each installer a publish leaves in the bucket, the newest first.
KEEP_VERSIONS = 3


def key(installer: Installer) -> str:
    """The fixed-name key an installer used to be stored at, before versions went in the name."""
    return _key(installer.platform, installer.filename)


def versioned_key(installer: Installer, version: str | None) -> str | None:
    """Where a version of an installer is stored: under the name it is saved as."""
    if not version or not _VERSION.match(version):
        return None
    return _key(installer.platform, download_name(installer, version))


def stored_key(installer: Installer, version: str | None, present: Iterable[str]) -> str | None:
    """The key to serve: the file named with its version, or -- for a release published before
    versions went in the name -- the one at the fixed name. None when neither is there."""
    held = set(present)
    for candidate in (versioned_key(installer, version), key(installer)):
        if candidate is not None and candidate in held:
            return candidate
    return None


def superseded(installer: Installer, keys: Iterable[str], current: str) -> list[str]:
    """What a publish of `current` may remove from the platform's folder: the file at the old
    fixed name, and every version but the newest KEEP_VERSIONS. `current` always stays, and so
    does anything that is not an installer (latest.json, someone's notes)."""
    path = PurePosixPath(installer.filename)
    named = re.compile(rf"^{re.escape(path.stem)}-(\d+)\.(\d+)\.(\d+){re.escape(path.suffix)}$")
    versions: list[tuple[tuple[int, ...], str]] = []
    stale = []
    for found in keys:
        if found == key(installer):
            stale.append(found)
            continue
        if matched := named.match(PurePosixPath(found).name):
            versions.append((tuple(int(part) for part in matched.groups()), found))
    newest = sorted(versions, reverse=True)[:KEEP_VERSIONS]
    kept = {found for _, found in newest} | {versioned_key(installer, current)}
    stale.extend(found for _, found in versions if found not in kept)
    return sorted(stale)


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
    if api_settings.DESKTOP_DOWNLOAD_PAGE_URL:
        return api_settings.DESKTOP_DOWNLOAD_PAGE_URL
    if api_settings.INVITATION_ACCEPT_URL:
        parsed = urlparse(api_settings.INVITATION_ACCEPT_URL)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}/download"
    return None


def folder() -> str:
    prefix = (settings.BUCKET_PREFIX or "").strip("/")
    return "/".join(part for part in [prefix, "downloads", "desktop"] if part) + "/"


def platform_folder(installer: Installer) -> str:
    """Everything stored for one platform: its installers and its latest.json."""
    return f"{folder()}{installer.platform}/"

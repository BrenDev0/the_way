"""A short signed link to an installer: what the public download page and the desktop app's own
update both hand out. The file is at one fixed key; the name it is saved as carries the version."""

import logging
from dataclasses import dataclass

from src.core.bucket.domain import BucketError
from src.core.bucket.ports import BucketStore
from src.core.exceptions import NotFoundError, ServiceUnavailableError

from . import config, versions

logger = logging.getLogger(__name__)


def unavailable(exc: BucketError) -> ServiceUnavailableError:
    """The bucket could not be read: the caller is told to try again, not given a 500, and the
    reason is logged."""
    logger.warning("The installers bucket could not be read: %s", exc)
    return ServiceUnavailableError(
        message="Las descargas no están disponibles en este momento. Inténtalo de nuevo en unos minutos.",
        code="downloads_unavailable",
    )


@dataclass(frozen=True)
class InstallerLink:
    url: str
    filename: str
    version: str | None


async def installer_link(bucket: BucketStore, platform: str) -> InstallerLink:
    installer = config.INSTALLERS.get(platform)
    try:
        published = installer is not None and await bucket.exists(config.key(installer))
    except BucketError as exc:
        raise unavailable(exc) from exc
    if installer is None or not published:
        raise NotFoundError(
            message="Ese instalador todavía no está publicado.", code="installer_not_published"
        )
    try:
        version = (await versions.published(bucket)).get(installer.platform)
        name = config.download_name(installer, version)
        url = await bucket.presign_get(config.key(installer), config.LINK_SECONDS, download_name=name)
    except BucketError as exc:
        raise unavailable(exc) from exc
    return InstallerLink(url=url, filename=name, version=version)

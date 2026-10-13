"""Which version each published installer is, read from the latest.json beside it."""

import json
import tempfile
import time
from pathlib import Path

from src.core.bucket.ports import BucketStore

from . import config

# Every desktop app asks when it starts and every few hours; the answer changes only
# when someone publishes, so the bucket is read at most this often.
CACHE_SECONDS = 5 * 60

_cache: tuple[float, dict[str, str | None]] | None = None


async def published(bucket: BucketStore) -> dict[str, str | None]:
    """{"windows": "0.1.1", "mac": None, ...}: None where nothing was recorded."""
    global _cache
    if _cache is not None and time.monotonic() - _cache[0] < CACHE_SECONDS:
        return _cache[1]

    present = {item.key for item in await bucket.list(config.folder())}
    found: dict[str, str | None] = {}
    with tempfile.TemporaryDirectory() as folder:
        for installer in config.INSTALLERS.values():
            key = config.version_key(installer)
            found[installer.platform] = None
            if key not in present:
                continue
            target = Path(folder) / f"{installer.platform}.json"
            try:
                await bucket.get(key, target)
                version = json.loads(target.read_text(encoding="utf-8")).get("version")
            except (OSError, ValueError):
                continue
            if isinstance(version, str):
                found[installer.platform] = version
    _cache = (time.monotonic(), found)
    return found


def forget() -> None:
    """Drops the cached answer: after a publish, or between tests."""
    global _cache
    _cache = None

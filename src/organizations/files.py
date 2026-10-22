import asyncio
from collections.abc import Sequence
from uuid import UUID

from src.core.bucket.ports import BucketStore

from . import keys
from .domain import FilesPurged

# Deleting is one request per object, so they go side by side; this many at once keeps a
# large organization quick without opening hundreds of connections.
DELETE_AT_ONCE = 25


async def purge_files(bucket: BucketStore, organization_id: UUID) -> FilesPurged:
    """Delete everything an organization has in the bucket, and only that: its prefix, which
    ends in the organization's id and a slash. A key outside the prefix is never deleted, even
    if the listing returned one.

    Idempotent: run again after a partial failure and it finishes the job. A bucket that cannot
    be listed raises `BucketError`; objects that could not be deleted are counted in `failed`.
    """
    prefix = keys.organization_prefix(organization_id)
    found = [item.key for item in await bucket.list(prefix) if item.key.startswith(prefix)]

    removed = 0
    failed = 0
    for batch in _batches(found, DELETE_AT_ONCE):
        results = await asyncio.gather(*(bucket.delete(key) for key in batch), return_exceptions=True)
        failed += sum(isinstance(result, BaseException) for result in results)
        removed += sum(not isinstance(result, BaseException) for result in results)
    return FilesPurged(removed=removed, failed=failed)


def _batches(items: Sequence[str], size: int) -> list[Sequence[str]]:
    return [items[start : start + size] for start in range(0, len(items), size)]

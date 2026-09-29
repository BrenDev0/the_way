from pathlib import Path

from .domain import BucketError, RemoteObject

UNAVAILABLE = "No bucket is configured for this run."


class UnavailableBucketStore:
    """Stands in when a run has no bucket, so file tools fail with a clear error instead
    of the whole run failing to start."""

    async def put(self, key: str, source: Path) -> RemoteObject:
        raise BucketError(UNAVAILABLE)

    async def get(self, key: str, destination: Path) -> Path:
        raise BucketError(UNAVAILABLE)

    async def list(self, prefix: str = "") -> list[RemoteObject]:
        raise BucketError(UNAVAILABLE)

    async def delete(self, key: str) -> None:
        raise BucketError(UNAVAILABLE)

    async def exists(self, key: str) -> bool:
        raise BucketError(UNAVAILABLE)

    async def copy(self, source_key: str, destination_key: str) -> None:
        raise BucketError(UNAVAILABLE)

    async def presign_put(self, key: str, content_type: str, expires_in: int) -> str:
        raise BucketError(UNAVAILABLE)

    async def presign_get(
        self, key: str, expires_in: int, download_name: str | None = None
    ) -> str:
        raise BucketError(UNAVAILABLE)

    async def aclose(self) -> None:
        return None

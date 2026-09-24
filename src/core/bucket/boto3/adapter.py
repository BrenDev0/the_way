import asyncio
from contextlib import AsyncExitStack
from pathlib import Path

import aioboto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from src.core.bucket.domain import BucketError, RemoteObject

CONNECT_TIMEOUT = 15
READ_TIMEOUT = 60

MISSING_CODES = {"404", "NoSuchKey", "NotFound"}


class Boto3BucketStore:
    def __init__(
        self,
        bucket: str,
        region: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        endpoint_url: str | None = None,
    ):
        if not bucket:
            raise BucketError("No bucket configured -- set BUCKET_NAME in your .env.")

        self._bucket = bucket
        self._session = aioboto3.Session(
            **_set(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
            )
        )
        self._options = _set(
            endpoint_url=endpoint_url,
            config=Config(connect_timeout=CONNECT_TIMEOUT, read_timeout=READ_TIMEOUT),
        )

        self._stack = AsyncExitStack()
        self._client = None
        self._opening = asyncio.Lock()

    @property
    def bucket(self) -> str:
        return self._bucket

    async def _s3(self):
        if self._client is not None:
            return self._client

        async with self._opening:
            if self._client is None:
                self._client = await self._stack.enter_async_context(
                    self._session.client("s3", **self._options)
                )

        return self._client

    async def put(self, key: str, source: Path) -> RemoteObject:
        client = await self._s3()

        with _wrapped(f"uploading {key}"):
            await client.upload_file(str(source), self._bucket, key)

        return RemoteObject(key=key, size=source.stat().st_size)

    async def get(self, key: str, destination: Path) -> Path:
        client = await self._s3()
        destination.parent.mkdir(parents=True, exist_ok=True)

        with _wrapped(f"downloading {key}", missing=f"'{key}' is not in the bucket."):
            await client.download_file(self._bucket, key, str(destination))

        return destination

    async def list(self, prefix: str = "") -> list[RemoteObject]:
        client = await self._s3()
        found: list[RemoteObject] = []

        with _wrapped(f"listing {prefix or '/'}"):
            paginator = client.get_paginator("list_objects_v2")

            async for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                found.extend(
                    RemoteObject(
                        key=item["Key"],
                        size=item["Size"],
                        modified=item.get("LastModified"),
                    )
                    for item in page.get("Contents", ())
                )

        return found

    async def delete(self, key: str) -> None:
        client = await self._s3()

        with _wrapped(f"deleting {key}"):
            await client.delete_object(Bucket=self._bucket, Key=key)

    async def exists(self, key: str) -> bool:
        client = await self._s3()

        try:
            await client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as exc:
            if _code(exc) in MISSING_CODES:
                return False
            raise BucketError(f"Could not check '{key}': {_reason(exc)}") from exc
        except BotoCoreError as exc:
            raise BucketError(f"Could not check '{key}': {exc}") from exc

    async def presign_put(self, key: str, content_type: str, expires_in: int) -> str:
        client = await self._s3()

        with _wrapped(f"preparing an upload for {key}"):
            return await client.generate_presigned_url(
                "put_object",
                Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=expires_in,
            )

    async def aclose(self) -> None:
        await self._stack.aclose()
        self._client = None


def _set(**options) -> dict:
    return {name: value for name, value in options.items() if value}


def _code(exc: ClientError) -> str:
    error = exc.response.get("Error", {})
    return str(error.get("Code", "")) or str(
        exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", "")
    )


def _reason(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Message", "")) or str(exc)


class _wrapped:
    def __init__(self, doing: str, missing: str = ""):
        self._doing = doing
        self._missing = missing

    def __enter__(self):
        return self

    def __exit__(self, kind, exc, traceback):
        if exc is None:
            return False

        if isinstance(exc, ClientError):
            if self._missing and _code(exc) in MISSING_CODES:
                raise BucketError(self._missing) from exc
            raise BucketError(f"Failed {self._doing}: {_reason(exc)}") from exc

        if isinstance(exc, BotoCoreError):
            raise BucketError(f"Failed {self._doing}: {exc}") from exc

        if isinstance(exc, OSError):
            raise BucketError(f"Failed {self._doing}: {exc}") from exc

        return False

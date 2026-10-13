"""Publishes a desktop installer: uploads it to the bucket, where the download page finds it.

    python -m src.downloads.publish windows ../the_way_desktop/out/make/squirrel.windows/x64/THE-WAY-Setup.exe
    python -m src.downloads.publish mac THE-WAY-darwin-arm64-0.1.0.zip

It writes to whichever bucket the BUCKET_* settings name -- for production, run it with
the production bucket's settings in the environment. The file replaces the one published
before; the page offers it as soon as the upload finishes.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from . import config


async def publish(platform: str, source: Path) -> str:
    from src.core.bucket.boto3.adapter import Boto3BucketStore
    from src.core.settings import settings

    if not settings.BUCKET_NAME:
        raise SystemExit("No bucket configured (BUCKET_NAME).")
    installer = config.INSTALLERS[platform]
    bucket = Boto3BucketStore(
        bucket=settings.BUCKET_NAME,
        region=settings.BUCKET_REGION,
        access_key=settings.BUCKET_ACCESS_KEY_ID,
        secret_key=settings.BUCKET_SECRET_ACCESS_KEY,
        endpoint_url=settings.BUCKET_ENDPOINT,
        public_endpoint_url=settings.BUCKET_PUBLIC_ENDPOINT,
    )
    try:
        stored = await bucket.put(config.key(installer), source)
    finally:
        await bucket.aclose()
    return f"{installer.label}: {stored.size / 1_000_000:.1f} MB -> {settings.BUCKET_NAME}/{stored.key}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("platform", choices=sorted(config.INSTALLERS))
    parser.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    if not args.file.is_file():
        print(f"Not a file: {args.file}", file=sys.stderr)
        return 1
    print(asyncio.run(publish(args.platform, args.file)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

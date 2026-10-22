"""Publishes a desktop installer: uploads it to the bucket, where the download page finds it.

    python -m src.downloads.publish windows THE-WAY-Setup.exe --version 0.1.1
    python -m src.downloads.publish mac THE-WAY-mac.zip --version 0.1.1

It writes to whichever bucket the BUCKET_* settings name -- for production, run it with
the production bucket's settings in the environment. The file replaces the one published
before; the page offers it as soon as the upload finishes. --version is the app's version
(`version` in the_way_desktop/package.json): it is recorded beside the file, and installed
apps older than it tell their operator a new version is out.
"""

import argparse
import asyncio
import json
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import config

VERSION = re.compile(r"^\d+\.\d+\.\d+$")


async def publish(platform: str, source: Path, version: str) -> str:
    from src.core.bucket.boto3.adapter import Boto3BucketStore
    from src.core.settings.shared import settings

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
        # after the file: an app told about a version must find its installer there
        with tempfile.TemporaryDirectory() as folder:
            record = Path(folder) / config.VERSION_FILE
            record.write_text(
                json.dumps({"version": version, "published_at": datetime.now(UTC).isoformat()}),
                encoding="utf-8",
            )
            await bucket.put(config.version_key(installer), record)
    finally:
        await bucket.aclose()
    return (
        f"{installer.label} {version}: {stored.size / 1_000_000:.1f} MB -> "
        f"{settings.BUCKET_NAME}/{stored.key}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("platform", choices=sorted(config.INSTALLERS))
    parser.add_argument("file", type=Path)
    parser.add_argument("--version", required=True, help="the app's version, e.g. 0.1.1")
    args = parser.parse_args(argv)
    if not args.file.is_file():
        print(f"Not a file: {args.file}", file=sys.stderr)
        return 1
    if not VERSION.match(args.version):
        print(f"Not a version like 0.1.1: {args.version}", file=sys.stderr)
        return 1
    print(asyncio.run(publish(args.platform, args.file, args.version)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Loads brand packs into an organization's library, as its owner or an admin would in the
panel. One folder per brand, with what the page builder reads (src/html_pages/brand.py):
tokens.css, identity.md, voice.md, logo/.

    python -m src.projects.load_brands --email owner@example.com --source ../the-way-kit/brand-packs
    python -m src.projects.load_brands --email owner@example.com --source ... --brand SLS --brand XST

Files already there are replaced, so running it again brings the library up to the pack.
Only owners and admins change the library; anyone else is refused, as in the panel.
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.bucket.ports import BucketStore
from src.core.cryptography.bcrypt.adapter import BcryptHashingService
from src.users.domain import Role, User
from src.users.sqlalchemy import adapter as users_adapter

from . import config, paths
from .files import content_type_for
from .sqlalchemy import adapter

# What a pack is made of; anything else in its folder (notes, drafts) stays out.
PACK_FILES = ("tokens.css", "identity.md", "voice.md", "brand.json", "sources.md")
LOGO_SUFFIXES = frozenset({".svg", ".png", ".webp", ".jpg", ".jpeg"})


class LoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class Loaded:
    brand: str
    files: list[str]


def pack_files(pack: Path) -> list[Path]:
    if not (pack / "tokens.css").is_file():
        raise LoadError(f"{pack.name}: no tokens.css, so it is not a brand pack")
    found = [pack / name for name in PACK_FILES if (pack / name).is_file()]
    logo = pack / "logo"
    if logo.is_dir():
        found += sorted(f for f in logo.iterdir() if f.suffix.lower() in LOGO_SUFFIXES)
    return found


IMAGE_TYPES = {".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _content_type(path: Path) -> str:
    return IMAGE_TYPES.get(path.suffix.lower()) or content_type_for(path.name)


async def find_editor(session: AsyncSession, email: str) -> User:
    hashing = BcryptHashingService()
    user = None
    for candidate in dict.fromkeys((email.strip(), email.strip().lower())):
        user = await users_adapter.get_user_by_email_hash(session, hashing.deterministic_hash(candidate))
        if user is not None:
            break
    if user is None:
        raise LoadError(f"No user with the email {email}")
    if user.role not in (Role.OWNER, Role.ADMIN):
        raise LoadError(f"{email} is {user.role}; only owners and admins change the library")
    return user


async def load(
    session: AsyncSession,
    bucket: BucketStore,
    organization_id: UUID,
    user_id: UUID,
    packs: list[Path],
) -> list[Loaded]:
    """Every pack is checked before anything is written, so a bad folder stops the run
    instead of leaving the library half loaded."""
    planned = [(pack.name, pack_files(pack), pack) for pack in packs]
    library = await adapter.get_or_create_library(session, organization_id, config.LIBRARY_PROJECT)

    async def find_entry(project_id, folder_id, name):
        return await adapter.find_entry(session, project_id, folder_id, name)

    loaded = []
    for brand, files, pack in planned:
        written = []
        for file in files:
            relative = file.relative_to(pack).as_posix()
            segments = [brand, *relative.split("/")]
            folder_id = await paths.ensure_folder(
                library, segments[:-1], find_entry,
                lambda folder: adapter.create_folder(session, folder),
            )
            await paths.store_file(
                project=library,
                folder_id=folder_id,
                name=segments[-1],
                content=file.read_bytes(),
                content_type=_content_type(file),
                uploaded_by=user_id,
                overwrite=True,
                find_entry_fn=find_entry,
                create_file_fn=lambda project_file: adapter.create_file(session, project_file),
                update_file_fn=lambda file_id, changes: adapter.update_file(session, file_id, changes),
                bucket_store=bucket,
            )
            written.append("/".join(segments))
        loaded.append(Loaded(brand, written))
    return loaded


def _packs(source: Path, brands: list[str]) -> list[Path]:
    if not source.is_dir():
        raise LoadError(f"{source} is not a folder")
    available = {p.name.upper(): p for p in source.iterdir() if p.is_dir()}
    if not brands:
        return [available[name] for name in sorted(available)]
    missing = [b for b in brands if b.upper() not in available]
    if missing:
        raise LoadError(f"Not in {source}: {', '.join(missing)}. There: {', '.join(sorted(available))}")
    return [available[b.upper()] for b in brands]


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--email", required=True, help="an owner or admin of the organization")
    parser.add_argument("--source", required=True, type=Path, help="the folder holding one folder per brand")
    parser.add_argument("--brand", action="append", default=[], help="only this brand (repeatable)")
    args = parser.parse_args(argv)

    from src.core.bucket.boto3.adapter import Boto3BucketStore
    from src.core.database.sqlalchemy.core import async_session_factory
    from src.core.settings import settings

    if not settings.BUCKET_NAME:
        print("No bucket configured (BUCKET_NAME)", file=sys.stderr)
        return 1
    bucket = Boto3BucketStore(
        bucket=settings.BUCKET_NAME,
        region=settings.BUCKET_REGION,
        access_key=settings.BUCKET_ACCESS_KEY_ID,
        secret_key=settings.BUCKET_SECRET_ACCESS_KEY,
        endpoint_url=settings.BUCKET_ENDPOINT,
        public_endpoint_url=settings.BUCKET_PUBLIC_ENDPOINT,
    )
    try:
        packs = _packs(args.source, args.brand)
        async with async_session_factory() as session:
            user = await find_editor(session, args.email)
            loaded = await load(session, bucket, user.organization_id, user.id, packs)
            await session.commit()
    except LoadError as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        await bucket.aclose()

    for item in loaded:
        print(f"{item.brand}: {len(item.files)} files -> {config.LIBRARY_PROJECT}/{item.brand}/")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

from pathlib import PurePosixPath
from uuid import UUID

from src.core.settings import settings


def document_key(organization_id: UUID, document_id: UUID, filename: str) -> str:
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()[:16]
    prefix = (settings.BUCKET_PREFIX or "").strip("/")
    parts = [prefix, "organizations", str(organization_id), "documents", f"{document_id}{suffix}"]
    return "/".join(part for part in parts if part)

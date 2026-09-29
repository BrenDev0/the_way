from uuid import UUID

from src.core.settings import settings


def file_key(organization_id: UUID, file_id: UUID) -> str:
    # Keyed by id alone so renaming or moving a file never touches the bucket.
    prefix = (settings.BUCKET_PREFIX or "").strip("/")
    parts = [prefix, "organizations", str(organization_id), "files", str(file_id)]
    return "/".join(part for part in parts if part)

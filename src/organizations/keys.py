from uuid import UUID

from src.core.settings.shared import settings


def organization_prefix(organization_id: UUID) -> str:
    """Where everything an organization has in the bucket lives: its project files and its
    documents, which projects.keys and documents.keys build beneath it. Ends with a slash, so
    one organization's prefix is never the start of another's."""
    prefix = (settings.BUCKET_PREFIX or "").strip("/")
    parts = [prefix, "organizations", str(organization_id)]
    return "/".join(part for part in parts if part) + "/"

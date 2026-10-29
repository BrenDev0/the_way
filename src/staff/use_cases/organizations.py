import logging
from collections.abc import Sequence
from uuid import UUID

from src.core.bucket.domain import BucketError
from src.core.cache.ports import CacheStore
from src.core.exceptions import NotFoundError, ValidationError
from src.invitations.ports import ListPendingForOrganizationFn
from src.organizations import use_cases as organizations_use_cases
from src.organizations.ports import DeleteOrganizationByIdFn
from src.staff.domain import (
    OrganizationDeletion,
    OrganizationDetail,
    OrganizationSummary,
)
from src.staff.ports import (
    GetOrganizationSummaryFn,
    ListOrganizationMembersFn,
    ListOrganizationSummariesFn,
    PurgeOrganizationFilesFn,
)

logger = logging.getLogger(__name__)


def _not_found() -> NotFoundError:
    return NotFoundError(message="Organization not found", code="organization_not_found")


async def list_organizations(
    list_organization_summaries_fn: ListOrganizationSummariesFn,
) -> Sequence[OrganizationSummary]:
    """Every organization, newest first, with its counts."""
    return await list_organization_summaries_fn()


async def get_organization(
    organization_id: UUID,
    get_organization_summary_fn: GetOrganizationSummaryFn,
    list_organization_members_fn: ListOrganizationMembersFn,
    list_pending_for_organization_fn: ListPendingForOrganizationFn,
) -> OrganizationDetail:
    """One organization, its people and its invitations that have not been answered. Read
    only: what staff see is who is there, never what they wrote or stored."""
    summary = await get_organization_summary_fn(organization_id)
    if summary is None:
        raise _not_found()

    return OrganizationDetail(
        summary=summary,
        members=await list_organization_members_fn(organization_id),
        pending_invitations=await list_pending_for_organization_fn(organization_id),
    )


async def delete_organization(
    organization_id: UUID,
    confirmation: str,
    get_organization_summary_fn: GetOrganizationSummaryFn,
    delete_organization_by_id_fn: DeleteOrganizationByIdFn,
    cache_store: CacheStore,
    purge_organization_files_fn: PurgeOrganizationFilesFn,
) -> OrganizationDeletion:
    """Delete an organization for good: its people, conversations, projects and everything it
    stored. Permanent, so the caller must type the organization's exact name.

    The order is deliberate. The database rows go first (one transaction, everything
    cascades), then the files in the bucket -- so there is never an organization whose files
    are gone but which still exists to be used. A bucket that cannot be reached does not stop
    the deletion: the files left behind are counted in what comes back, and logged.
    """
    summary = await get_organization_summary_fn(organization_id)
    if summary is None:
        raise _not_found()

    if confirmation.strip() != summary.name.strip():
        raise ValidationError(
            message="Type the organization's exact name to confirm",
            code="confirmation_mismatch",
        )

    await organizations_use_cases.delete_organization(
        organization_id=organization_id,
        delete_organization_by_id_fn=delete_organization_by_id_fn,
        cache_store=cache_store,
    )

    files_removed = 0
    files_left: int | None
    try:
        purged = await purge_organization_files_fn(organization_id)
        files_removed, files_left = purged.removed, purged.failed
    except BucketError as exc:
        # None says nobody can tell what is left: the bucket was not listed
        files_left = None
        logger.warning("Could not clear the files of deleted organization %s: %s", organization_id, exc)

    if files_left:
        logger.warning("%s files of deleted organization %s were left in the bucket", files_left, organization_id)

    return OrganizationDeletion(
        organization_name=summary.name,
        members=summary.members,
        files=summary.files,
        bytes=summary.bytes,
        files_removed=files_removed,
        files_left=files_left,
    )

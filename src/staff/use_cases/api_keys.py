"""The provider keys of an organization, from the staff side. An organization uses the keys
Xplorers sets for it; nobody inside the organization issues, sees or removes one."""

from collections.abc import Sequence
from uuid import UUID

from src.api_keys import use_cases as api_keys_use_cases
from src.api_keys.domain import ApiKey, Provider
from src.api_keys.ports import DeleteApiKeyFn, ListApiKeysFn, UpsertApiKeyFn
from src.core.cryptography.ports import EncryptionService
from src.core.exceptions import NotFoundError
from src.staff.domain import StaffMember
from src.staff.ports import GetOrganizationSummaryFn


async def _require_organization(
    organization_id: UUID, get_organization_summary_fn: GetOrganizationSummaryFn
) -> None:
    if await get_organization_summary_fn(organization_id) is None:
        raise NotFoundError(message="Organization not found", code="organization_not_found")


async def list_api_keys(
    organization_id: UUID,
    get_organization_summary_fn: GetOrganizationSummaryFn,
    list_api_keys_fn: ListApiKeysFn,
) -> Sequence[ApiKey]:
    await _require_organization(organization_id, get_organization_summary_fn)
    return await api_keys_use_cases.list_api_keys(organization_id, list_api_keys_fn)


async def set_api_key(
    staff: StaffMember,
    organization_id: UUID,
    provider: Provider,
    secret: str,
    account_id: str | None,
    model: str | None,
    get_organization_summary_fn: GetOrganizationSummaryFn,
    upsert_api_key_fn: UpsertApiKeyFn,
    encryption_service: EncryptionService,
) -> ApiKey:
    """Sets or replaces the key for one provider. The secret goes in once and is only ever
    shown again as its last four characters."""
    await _require_organization(organization_id, get_organization_summary_fn)
    return await api_keys_use_cases.set_api_key(
        organization_id=organization_id,
        provider=provider,
        secret=secret,
        account_id=account_id,
        model=model,
        set_by=staff.id,
        upsert_api_key_fn=upsert_api_key_fn,
        encryption_service=encryption_service,
    )


async def delete_api_key(
    organization_id: UUID,
    provider: Provider,
    get_organization_summary_fn: GetOrganizationSummaryFn,
    delete_api_key_fn: DeleteApiKeyFn,
) -> None:
    await _require_organization(organization_id, get_organization_summary_fn)
    await api_keys_use_cases.delete_api_key(organization_id, provider, delete_api_key_fn)

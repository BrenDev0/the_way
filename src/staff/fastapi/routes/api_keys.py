"""An organization's provider keys, set by Xplorers staff. Write only: a key goes in and comes
back as its last four characters, never in full."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from src.api_keys.domain import Provider
from src.api_keys.fastapi import dependencies as api_keys_dependencies
from src.api_keys.ports import DeleteApiKeyFn, ListApiKeysFn, UpsertApiKeyFn
from src.core.cryptography.ports import EncryptionService
from src.fastapi import dependencies as api_dependencies
from src.staff.domain import StaffMember
from src.staff.ports import GetOrganizationSummaryFn
from src.staff.use_cases import api_keys as use_cases

from .. import dependencies as staff_dependencies
from ..schemas import (
    DeleteOrganizationApiKeyResponse,
    OrganizationApiKeyResponse,
    SetApiKeyRequest,
    tolerant_decrypt,
)

router = APIRouter(tags=["staff"])

CurrentStaff = Annotated[StaffMember, Depends(staff_dependencies.get_current_staff)]
Encryption = Annotated[EncryptionService, Depends(api_dependencies.get_encryption_service)]
GetSummary = Annotated[
    GetOrganizationSummaryFn,
    Depends(staff_dependencies.provide_get_organization_summary_fn),
]


@router.get("/{organization_id}/api-keys", response_model=list[OrganizationApiKeyResponse])
async def list_api_keys_route(
    organization_id: UUID,
    staff: CurrentStaff,
    encryption_service: Encryption,
    get_organization_summary_fn: GetSummary,
    list_api_keys_fn: Annotated[ListApiKeysFn, Depends(api_keys_dependencies.provide_list_api_keys_fn)],
) -> list[OrganizationApiKeyResponse]:
    decrypt = tolerant_decrypt(encryption_service)
    keys = await use_cases.list_api_keys(organization_id, get_organization_summary_fn, list_api_keys_fn)
    return [OrganizationApiKeyResponse.from_domain(key, decrypt) for key in keys]


@router.put("/{organization_id}/api-keys/{provider}", response_model=OrganizationApiKeyResponse)
async def set_api_key_route(
    organization_id: UUID,
    provider: Provider,
    payload: SetApiKeyRequest,
    staff: CurrentStaff,
    encryption_service: Encryption,
    get_organization_summary_fn: GetSummary,
    upsert_api_key_fn: Annotated[UpsertApiKeyFn, Depends(api_keys_dependencies.provide_upsert_api_key_fn)],
) -> OrganizationApiKeyResponse:
    key = await use_cases.set_api_key(
        staff=staff,
        organization_id=organization_id,
        provider=provider,
        secret=payload.secret,
        account_id=payload.account_id,
        model=payload.model,
        get_organization_summary_fn=get_organization_summary_fn,
        upsert_api_key_fn=upsert_api_key_fn,
        encryption_service=encryption_service,
    )
    return OrganizationApiKeyResponse.from_domain(key, tolerant_decrypt(encryption_service))


@router.delete("/{organization_id}/api-keys/{provider}", response_model=DeleteOrganizationApiKeyResponse)
async def delete_api_key_route(
    organization_id: UUID,
    provider: Provider,
    staff: CurrentStaff,
    get_organization_summary_fn: GetSummary,
    delete_api_key_fn: Annotated[DeleteApiKeyFn, Depends(api_keys_dependencies.provide_delete_api_key_fn)],
) -> DeleteOrganizationApiKeyResponse:
    await use_cases.delete_api_key(organization_id, provider, get_organization_summary_fn, delete_api_key_fn)
    return DeleteOrganizationApiKeyResponse(detail="API key deleted")

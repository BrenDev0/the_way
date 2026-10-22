"""Every organization, as Xplorers staff see them: the list, one organization's people, and
deleting one. Read only except for the delete, which is permanent and kept on record."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from src.core.cache.ports import CacheStore
from src.core.cryptography.ports import EncryptionService
from src.fastapi import dependencies as api_dependencies
from src.invitations.fastapi import dependencies as invitations_dependencies
from src.invitations.ports import ListPendingForOrganizationFn
from src.organizations.fastapi import dependencies as organizations_dependencies
from src.organizations.ports import DeleteOrganizationByIdFn
from src.staff.domain import StaffMember
from src.staff.ports import (
    GetOrganizationSummaryFn,
    ListDeletedOrganizationsFn,
    ListOrganizationMembersFn,
    ListOrganizationSummariesFn,
    PurgeOrganizationFilesFn,
    RecordDeletedOrganizationFn,
)
from src.staff.use_cases import organizations as use_cases

from .. import dependencies as staff_dependencies
from ..schemas import (
    DeletedOrganizationResponse,
    DeleteOrganizationRequest,
    OrganizationDetailResponse,
    OrganizationSummaryResponse,
    tolerant_decrypt,
)

router = APIRouter(tags=["staff"])

CurrentStaff = Annotated[StaffMember, Depends(staff_dependencies.get_current_staff)]
Encryption = Annotated[EncryptionService, Depends(api_dependencies.get_encryption_service)]
GetSummary = Annotated[
    GetOrganizationSummaryFn,
    Depends(staff_dependencies.provide_get_organization_summary_fn),
]


@router.get("", response_model=list[OrganizationSummaryResponse])
async def list_organizations_route(
    staff: CurrentStaff,
    encryption_service: Encryption,
    list_organization_summaries_fn: Annotated[
        ListOrganizationSummariesFn,
        Depends(staff_dependencies.provide_list_organization_summaries_fn),
    ],
) -> list[OrganizationSummaryResponse]:
    decrypt = tolerant_decrypt(encryption_service)
    summaries = await use_cases.list_organizations(list_organization_summaries_fn)
    return [
        OrganizationSummaryResponse.from_domain(
            summary,
            owner_email=decrypt(summary.owner_encrypted_email) if summary.owner_encrypted_email else None,
        )
        for summary in summaries
    ]


# Before /{organization_id}, which would otherwise take "deleted" for an id.
@router.get("/deleted", response_model=list[DeletedOrganizationResponse])
async def list_deleted_organizations_route(
    staff: CurrentStaff,
    encryption_service: Encryption,
    list_deleted_organizations_fn: Annotated[
        ListDeletedOrganizationsFn,
        Depends(staff_dependencies.provide_list_deleted_organizations_fn),
    ],
) -> list[DeletedOrganizationResponse]:
    decrypt = tolerant_decrypt(encryption_service)
    records = await use_cases.list_deleted_organizations(list_deleted_organizations_fn)
    return [
        DeletedOrganizationResponse.from_domain(record, deleted_by_email=decrypt(record.deleted_by_encrypted_email))
        for record in records
    ]


@router.get("/{organization_id}", response_model=OrganizationDetailResponse)
async def get_organization_route(
    organization_id: UUID,
    staff: CurrentStaff,
    encryption_service: Encryption,
    get_organization_summary_fn: GetSummary,
    list_organization_members_fn: Annotated[
        ListOrganizationMembersFn,
        Depends(staff_dependencies.provide_list_organization_members_fn),
    ],
    list_pending_for_organization_fn: Annotated[
        ListPendingForOrganizationFn,
        Depends(invitations_dependencies.provide_list_pending_for_organization_fn),
    ],
) -> OrganizationDetailResponse:
    detail = await use_cases.get_organization(
        organization_id=organization_id,
        get_organization_summary_fn=get_organization_summary_fn,
        list_organization_members_fn=list_organization_members_fn,
        list_pending_for_organization_fn=list_pending_for_organization_fn,
    )
    return OrganizationDetailResponse.from_domain(detail, decrypt=tolerant_decrypt(encryption_service))


@router.delete("/{organization_id}", response_model=DeletedOrganizationResponse)
async def delete_organization_route(
    organization_id: UUID,
    payload: DeleteOrganizationRequest,
    staff: CurrentStaff,
    encryption_service: Encryption,
    cache_store: Annotated[CacheStore, Depends(api_dependencies.get_cache_store)],
    get_organization_summary_fn: GetSummary,
    delete_organization_by_id_fn: Annotated[
        DeleteOrganizationByIdFn,
        Depends(organizations_dependencies.provide_delete_organization_by_id_fn),
    ],
    purge_organization_files_fn: Annotated[
        PurgeOrganizationFilesFn,
        Depends(staff_dependencies.provide_purge_organization_files_fn),
    ],
    record_deleted_organization_fn: Annotated[
        RecordDeletedOrganizationFn,
        Depends(staff_dependencies.provide_record_deleted_organization_fn),
    ],
) -> DeletedOrganizationResponse:
    record = await use_cases.delete_organization(
        staff=staff,
        organization_id=organization_id,
        confirmation=payload.confirmation,
        get_organization_summary_fn=get_organization_summary_fn,
        delete_organization_by_id_fn=delete_organization_by_id_fn,
        cache_store=cache_store,
        purge_organization_files_fn=purge_organization_files_fn,
        record_deleted_organization_fn=record_deleted_organization_fn,
    )
    return DeletedOrganizationResponse.from_domain(
        record, deleted_by_email=tolerant_decrypt(encryption_service)(record.deleted_by_encrypted_email)
    )

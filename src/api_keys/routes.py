from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from src.api import dependencies as api_dependencies
from src.auth import dependencies as auth_dependencies
from src.core.cryptography.ports import EncryptionService
from src.users import dependencies as users_dependencies
from src.users.domain import Role, User
from src.users.ports import GetUserByIdFn

from . import dependencies as api_keys_dependencies
from . import mapper
from . import use_cases as api_keys_use_cases
from .ports import DeleteApiKeyForOrganizationFn, ListApiKeysFn, UpsertApiKeyFn
from .schemas import ApiKeyResponse, DeleteApiKeyResponse, IssueApiKeyRequest

router = APIRouter(tags=["api-keys"])

CurrentUser = Annotated[
    User,
    Depends(auth_dependencies.require_role(Role.OWNER, Role.ADMIN)),
]


@router.post("", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def issue_api_key_route(
    payload: IssueApiKeyRequest,
    current_user: CurrentUser,
    get_user_by_id_fn: Annotated[
        GetUserByIdFn,
        Depends(users_dependencies.provide_get_user_by_id_fn),
    ],
    upsert_api_key_fn: Annotated[
        UpsertApiKeyFn,
        Depends(api_keys_dependencies.provide_upsert_api_key_fn),
    ],
    encryption_service: Annotated[
        EncryptionService,
        Depends(api_dependencies.get_encryption_service),
    ],
) -> ApiKeyResponse:
    api_key = await api_keys_use_cases.issue_api_key(
        organization_id=current_user.organization_id,
        user_id=payload.user_id,
        provider=payload.provider,
        secret=payload.secret,
        account_id=payload.account_id,
        model=payload.model,
        issued_by=current_user.id,
        get_user_by_id_fn=get_user_by_id_fn,
        upsert_api_key_fn=upsert_api_key_fn,
        encryption_service=encryption_service,
    )
    return mapper.domain_to_api_key_response(api_key)


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys_route(
    current_user: CurrentUser,
    list_api_keys_fn: Annotated[
        ListApiKeysFn,
        Depends(api_keys_dependencies.provide_list_api_keys_fn),
    ],
    user_id: Annotated[UUID | None, Query(alias="userId")] = None,
) -> list[ApiKeyResponse]:
    api_keys = await api_keys_use_cases.list_api_keys(
        organization_id=current_user.organization_id,
        user_id=user_id,
        list_api_keys_fn=list_api_keys_fn,
    )
    return [mapper.domain_to_api_key_response(key) for key in api_keys]


@router.delete("/{api_key_id}", response_model=DeleteApiKeyResponse)
async def delete_api_key_route(
    api_key_id: UUID,
    current_user: CurrentUser,
    delete_api_key_for_organization_fn: Annotated[
        DeleteApiKeyForOrganizationFn,
        Depends(api_keys_dependencies.provide_delete_api_key_for_organization_fn),
    ],
) -> DeleteApiKeyResponse:
    await api_keys_use_cases.delete_api_key(
        api_key_id=api_key_id,
        organization_id=current_user.organization_id,
        delete_api_key_for_organization_fn=delete_api_key_for_organization_fn,
    )
    return DeleteApiKeyResponse(detail="API key deleted")

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from src.api import dependencies as api_dependencies
from src.auth import dependencies as auth_dependencies
from src.core.cache.ports import CacheStore
from src.core.sessions.config import SessionCookieConfig
from src.users import dependencies as users_dependencies
from src.users.domain import Role, User
from src.users.ports import GetUserByIdFn, UpdateUserRoleFn

from . import dependencies as organizations_dependencies
from . import mapper
from . import use_cases as organizations_use_cases
from .ports import (
    DeleteOrganizationByIdFn,
    GetOrganizationByIdFn,
    UpdateOrganizationByIdFn,
)
from .schemas import (
    DeleteOrganizationResponse,
    OrganizationResponse,
    TransferOwnershipRequest,
    TransferOwnershipResponse,
    UpdateOrganizationRequest,
)

router = APIRouter(tags=["organizations"])


@router.get("/me", response_model=OrganizationResponse)
async def get_current_organization_route(
    current_user: Annotated[
        User,
        Depends(auth_dependencies.require_role(Role.OWNER, Role.ADMIN, Role.MEMBER)),
    ],
    get_organization_by_id_fn: Annotated[
        GetOrganizationByIdFn,
        Depends(organizations_dependencies.provide_get_organization_by_id_fn),
    ],
    cache_store: Annotated[CacheStore, Depends(api_dependencies.get_cache_store)],
) -> OrganizationResponse:
    organization = await organizations_use_cases.get_organization(
        organization_id=current_user.organization_id,
        get_organization_by_id_fn=get_organization_by_id_fn,
        cache_store=cache_store,
    )
    return mapper.domain_to_organization_response(organization)


@router.patch("/me", response_model=OrganizationResponse)
async def update_current_organization_route(
    payload: UpdateOrganizationRequest,
    current_user: Annotated[
        User,
        Depends(auth_dependencies.require_role(Role.OWNER, Role.ADMIN)),
    ],
    update_organization_by_id_fn: Annotated[
        UpdateOrganizationByIdFn,
        Depends(organizations_dependencies.provide_update_organization_by_id_fn),
    ],
    cache_store: Annotated[CacheStore, Depends(api_dependencies.get_cache_store)],
) -> OrganizationResponse:
    organization = await organizations_use_cases.rename_organization(
        organization_id=current_user.organization_id,
        name=payload.name,
        update_organization_by_id_fn=update_organization_by_id_fn,
        cache_store=cache_store,
    )
    return mapper.domain_to_organization_response(organization)


@router.delete("/me", response_model=DeleteOrganizationResponse)
async def delete_current_organization_route(
    response: Response,
    current_user: Annotated[User, Depends(auth_dependencies.require_role(Role.OWNER))],
    delete_organization_by_id_fn: Annotated[
        DeleteOrganizationByIdFn,
        Depends(organizations_dependencies.provide_delete_organization_by_id_fn),
    ],
    cache_store: Annotated[CacheStore, Depends(api_dependencies.get_cache_store)],
    session_cookie_config: Annotated[
        SessionCookieConfig,
        Depends(api_dependencies.get_session_cookie_config),
    ],
) -> DeleteOrganizationResponse:
    await organizations_use_cases.delete_organization(
        organization_id=current_user.organization_id,
        delete_organization_by_id_fn=delete_organization_by_id_fn,
        cache_store=cache_store,
    )

    response.delete_cookie(
        key=session_cookie_config.name,
        path=session_cookie_config.path,
        secure=session_cookie_config.secure,
        httponly=session_cookie_config.httponly,
        samesite=session_cookie_config.samesite,
    )
    return DeleteOrganizationResponse(detail="Organization deleted")


@router.post("/me/transfer-ownership", response_model=TransferOwnershipResponse)
async def transfer_ownership_route(
    payload: TransferOwnershipRequest,
    current_user: Annotated[User, Depends(auth_dependencies.require_role(Role.OWNER))],
    get_user_by_id_fn: Annotated[
        GetUserByIdFn,
        Depends(users_dependencies.provide_get_user_by_id_fn),
    ],
    update_user_role_fn: Annotated[
        UpdateUserRoleFn,
        Depends(users_dependencies.provide_update_user_role_fn),
    ],
    cache_store: Annotated[CacheStore, Depends(api_dependencies.get_cache_store)],
) -> TransferOwnershipResponse:
    await organizations_use_cases.transfer_ownership(
        organization_id=current_user.organization_id,
        current_owner_id=current_user.id,
        new_owner_id=payload.new_owner_id,
        get_user_by_id_fn=get_user_by_id_fn,
        update_user_role_fn=update_user_role_fn,
        cache_store=cache_store,
    )
    return TransferOwnershipResponse(detail="Ownership transferred")

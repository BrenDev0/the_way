"""The owner's side of an invitation from Xplorers: the one public route, reached with the
link's token. Accepting creates the organization and its owner together."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from src.core.cryptography.ports import EncryptionService, HashingService
from src.fastapi import dependencies as api_dependencies
from src.organizations.fastapi import dependencies as organizations_dependencies
from src.organizations.ports import CreateOrganizationFn
from src.staff.ports import ClaimOwnerInvitationFn, GetOwnerInvitationByTokenHashFn
from src.staff.use_cases import owner_invitations as use_cases
from src.users.fastapi import dependencies as users_dependencies
from src.users.fastapi.schemas import UserResponse
from src.users.ports import CreateUserFn, GetUserByEmailHashFn

from .. import dependencies as staff_dependencies
from ..schemas import AcceptOwnerInvitationRequest

router = APIRouter(tags=["staff"])


@router.post("/accept", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def accept_owner_invitation_route(
    payload: AcceptOwnerInvitationRequest,
    hashing_service: Annotated[HashingService, Depends(api_dependencies.get_hashing_service)],
    encryption_service: Annotated[EncryptionService, Depends(api_dependencies.get_encryption_service)],
    get_user_by_email_hash_fn: Annotated[
        GetUserByEmailHashFn,
        Depends(users_dependencies.provide_get_user_by_email_hash_fn),
    ],
    create_organization_fn: Annotated[
        CreateOrganizationFn,
        Depends(organizations_dependencies.provide_create_organization_fn),
    ],
    create_user_fn: Annotated[CreateUserFn, Depends(users_dependencies.provide_create_user_fn)],
    get_owner_invitation_by_token_hash_fn: Annotated[
        GetOwnerInvitationByTokenHashFn,
        Depends(staff_dependencies.provide_get_owner_invitation_by_token_hash_fn),
    ],
    claim_owner_invitation_fn: Annotated[
        ClaimOwnerInvitationFn,
        Depends(staff_dependencies.provide_claim_owner_invitation_fn),
    ],
) -> UserResponse:
    invitation = await use_cases.resolve_owner_invitation(
        token=payload.token,
        get_owner_invitation_by_token_hash_fn=get_owner_invitation_by_token_hash_fn,
        hashing_service=hashing_service,
    )
    _, user = await use_cases.accept_owner_invitation(
        invitation=invitation,
        password=payload.password,
        get_user_by_email_hash_fn=get_user_by_email_hash_fn,
        create_organization_fn=create_organization_fn,
        claim_owner_invitation_fn=claim_owner_invitation_fn,
        create_user_fn=create_user_fn,
        hashing_service=hashing_service,
    )
    return UserResponse.from_domain(
        user,
        email=encryption_service.decrypt(user.encrypted_email),
        setup_complete=False,
    )

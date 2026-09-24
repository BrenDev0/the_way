from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from src.api import dependencies as api_dependencies
from src.auth import dependencies as auth_dependencies
from src.core.cache.ports import CacheStore
from src.core.communications.ports import EmailSender
from src.core.cryptography.ports import EncryptionService, HashingService
from src.core.settings import settings
from src.organizations import dependencies as organizations_dependencies
from src.organizations import use_cases as organizations_use_cases
from src.organizations.ports import GetOrganizationByIdFn
from src.users import dependencies as users_dependencies
from src.users import mapper as users_mapper
from src.users.domain import Role, User
from src.users.ports import (
    CountUsersForOrganizationFn,
    CreateUserFn,
    GetUserByEmailHashFn,
)
from src.users.schemas import UserResponse

from . import dependencies as invitations_dependencies
from . import mapper
from . import use_cases as invitations_use_cases
from .ports import (
    AcceptInvitationFn,
    CountPendingForOrganizationFn,
    CreateInvitationFn,
    GetInvitationByTokenHashFn,
    ListPendingForOrganizationFn,
    RevokeInvitationFn,
    RevokePendingForEmailFn,
)
from .schemas import (
    AcceptInvitationRequest,
    CreateInvitationRequest,
    InvitationResponse,
    RevokeInvitationResponse,
)

router = APIRouter(tags=["invitations"])

CurrentUser = Annotated[
    User,
    Depends(auth_dependencies.require_role(Role.OWNER, Role.ADMIN)),
]
Encryption = Annotated[EncryptionService, Depends(api_dependencies.get_encryption_service)]
Hashing = Annotated[HashingService, Depends(api_dependencies.get_hashing_service)]
Cache = Annotated[CacheStore, Depends(api_dependencies.get_cache_store)]
GetOrganization = Annotated[
    GetOrganizationByIdFn,
    Depends(organizations_dependencies.provide_get_organization_by_id_fn),
]
GetUserByEmailHash = Annotated[
    GetUserByEmailHashFn,
    Depends(users_dependencies.provide_get_user_by_email_hash_fn),
]
CountUsers = Annotated[
    CountUsersForOrganizationFn,
    Depends(users_dependencies.provide_count_users_for_organization_fn),
]
CountPending = Annotated[
    CountPendingForOrganizationFn,
    Depends(invitations_dependencies.provide_count_pending_for_organization_fn),
]


@router.post("", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation_route(
    payload: CreateInvitationRequest,
    current_user: CurrentUser,
    encryption_service: Encryption,
    hashing_service: Hashing,
    cache_store: Cache,
    get_organization_by_id_fn: GetOrganization,
    get_user_by_email_hash_fn: GetUserByEmailHash,
    count_users_for_organization_fn: CountUsers,
    count_pending_for_organization_fn: CountPending,
    revoke_pending_for_email_fn: Annotated[
        RevokePendingForEmailFn,
        Depends(invitations_dependencies.provide_revoke_pending_for_email_fn),
    ],
    create_invitation_fn: Annotated[
        CreateInvitationFn,
        Depends(invitations_dependencies.provide_create_invitation_fn),
    ],
    email_sender: Annotated[EmailSender, Depends(api_dependencies.get_email_sender)],
) -> InvitationResponse:
    organization = await organizations_use_cases.get_organization(
        organization_id=current_user.organization_id,
        get_organization_by_id_fn=get_organization_by_id_fn,
        cache_store=cache_store,
    )

    invitation = await invitations_use_cases.invite_user(
        organization=organization,
        inviter=current_user,
        email=payload.email,
        role=payload.role,
        get_user_by_email_hash_fn=get_user_by_email_hash_fn,
        count_users_for_organization_fn=count_users_for_organization_fn,
        count_pending_for_organization_fn=count_pending_for_organization_fn,
        revoke_pending_for_email_fn=revoke_pending_for_email_fn,
        create_invitation_fn=create_invitation_fn,
        email_sender=email_sender,
        hashing_service=hashing_service,
        encryption_service=encryption_service,
        accept_url=settings.require_invitation_accept_url(),
    )
    return mapper.domain_to_invitation_response(invitation, encryption_service)


@router.get("", response_model=list[InvitationResponse])
async def list_invitations_route(
    current_user: CurrentUser,
    encryption_service: Encryption,
    list_pending_for_organization_fn: Annotated[
        ListPendingForOrganizationFn,
        Depends(invitations_dependencies.provide_list_pending_for_organization_fn),
    ],
) -> list[InvitationResponse]:
    invitations = await invitations_use_cases.list_invitations(
        organization_id=current_user.organization_id,
        list_pending_for_organization_fn=list_pending_for_organization_fn,
    )
    return [
        mapper.domain_to_invitation_response(invitation, encryption_service)
        for invitation in invitations
    ]


@router.delete("/{invitation_id}", response_model=RevokeInvitationResponse)
async def revoke_invitation_route(
    invitation_id: UUID,
    current_user: CurrentUser,
    revoke_invitation_fn: Annotated[
        RevokeInvitationFn,
        Depends(invitations_dependencies.provide_revoke_invitation_fn),
    ],
) -> RevokeInvitationResponse:
    await invitations_use_cases.revoke_invitation(
        invitation_id=invitation_id,
        organization_id=current_user.organization_id,
        revoke_invitation_fn=revoke_invitation_fn,
    )
    return RevokeInvitationResponse(detail="Invitation revoked")


@router.post("/accept", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def accept_invitation_route(
    payload: AcceptInvitationRequest,
    encryption_service: Encryption,
    hashing_service: Hashing,
    cache_store: Cache,
    get_organization_by_id_fn: GetOrganization,
    get_user_by_email_hash_fn: GetUserByEmailHash,
    count_users_for_organization_fn: CountUsers,
    count_pending_for_organization_fn: CountPending,
    get_invitation_by_token_hash_fn: Annotated[
        GetInvitationByTokenHashFn,
        Depends(invitations_dependencies.provide_get_invitation_by_token_hash_fn),
    ],
    create_user_fn: Annotated[
        CreateUserFn,
        Depends(users_dependencies.provide_create_user_fn),
    ],
    accept_invitation_fn: Annotated[
        AcceptInvitationFn,
        Depends(invitations_dependencies.provide_accept_invitation_fn),
    ],
) -> UserResponse:
    invitation = await invitations_use_cases.resolve_invitation(
        token=payload.token,
        get_invitation_by_token_hash_fn=get_invitation_by_token_hash_fn,
        hashing_service=hashing_service,
    )

    organization = await organizations_use_cases.get_organization(
        organization_id=invitation.organization_id,
        get_organization_by_id_fn=get_organization_by_id_fn,
        cache_store=cache_store,
    )

    user = await invitations_use_cases.accept_invitation(
        token=payload.token,
        password=payload.password,
        organization=organization,
        invitation=invitation,
        get_user_by_email_hash_fn=get_user_by_email_hash_fn,
        count_users_for_organization_fn=count_users_for_organization_fn,
        count_pending_for_organization_fn=count_pending_for_organization_fn,
        create_user_fn=create_user_fn,
        accept_invitation_fn=accept_invitation_fn,
        hashing_service=hashing_service,
    )
    return users_mapper.domain_to_user_response(user, encryption_service)

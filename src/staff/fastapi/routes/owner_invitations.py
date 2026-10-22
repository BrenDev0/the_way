"""Owner invitations, sent by Xplorers staff: the only way an organization, and its first
owner, comes to exist."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from src.core.communications.ports import EmailSender
from src.core.cryptography.ports import EncryptionService, HashingService
from src.core.settings.api import settings as api_settings
from src.fastapi import dependencies as api_dependencies
from src.staff.domain import StaffMember
from src.staff.ports import (
    CreateOwnerInvitationFn,
    ListOwnerInvitationsFn,
    RevokeOwnerInvitationFn,
    RevokePendingOwnerInvitationsForEmailFn,
)
from src.staff.use_cases import owner_invitations as use_cases
from src.users.fastapi import dependencies as users_dependencies
from src.users.ports import GetUserByEmailHashFn

from .. import dependencies as staff_dependencies
from ..schemas import (
    CreateOwnerInvitationRequest,
    OwnerInvitationResponse,
    RevokeOwnerInvitationResponse,
)

router = APIRouter(tags=["staff"])

CurrentStaff = Annotated[StaffMember, Depends(staff_dependencies.get_current_staff)]
Encryption = Annotated[EncryptionService, Depends(api_dependencies.get_encryption_service)]


@router.post("", response_model=OwnerInvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_owner_invitation_route(
    payload: CreateOwnerInvitationRequest,
    staff: CurrentStaff,
    encryption_service: Encryption,
    hashing_service: Annotated[HashingService, Depends(api_dependencies.get_hashing_service)],
    email_sender: Annotated[EmailSender, Depends(api_dependencies.get_email_sender)],
    get_user_by_email_hash_fn: Annotated[
        GetUserByEmailHashFn,
        Depends(users_dependencies.provide_get_user_by_email_hash_fn),
    ],
    revoke_pending_for_email_fn: Annotated[
        RevokePendingOwnerInvitationsForEmailFn,
        Depends(staff_dependencies.provide_revoke_pending_owner_invitations_for_email_fn),
    ],
    create_owner_invitation_fn: Annotated[
        CreateOwnerInvitationFn,
        Depends(staff_dependencies.provide_create_owner_invitation_fn),
    ],
) -> OwnerInvitationResponse:
    invitation = await use_cases.invite_owner(
        staff=staff,
        organization_name=payload.organization_name,
        email=payload.email,
        seat_limit=payload.seat_limit,
        get_user_by_email_hash_fn=get_user_by_email_hash_fn,
        revoke_pending_for_email_fn=revoke_pending_for_email_fn,
        create_owner_invitation_fn=create_owner_invitation_fn,
        email_sender=email_sender,
        hashing_service=hashing_service,
        encryption_service=encryption_service,
        accept_url=api_settings.require_owner_invitation_accept_url(),
    )
    return OwnerInvitationResponse.from_domain(
        invitation, email=encryption_service.decrypt(invitation.encrypted_email)
    )


@router.get("", response_model=list[OwnerInvitationResponse])
async def list_owner_invitations_route(
    staff: CurrentStaff,
    encryption_service: Encryption,
    list_owner_invitations_fn: Annotated[
        ListOwnerInvitationsFn,
        Depends(staff_dependencies.provide_list_owner_invitations_fn),
    ],
) -> list[OwnerInvitationResponse]:
    invitations = await use_cases.list_owner_invitations(list_owner_invitations_fn)
    return [
        OwnerInvitationResponse.from_domain(
            invitation, email=encryption_service.decrypt(invitation.encrypted_email)
        )
        for invitation in invitations
    ]


@router.delete("/{invitation_id}", response_model=RevokeOwnerInvitationResponse)
async def revoke_owner_invitation_route(
    invitation_id: UUID,
    staff: CurrentStaff,
    revoke_owner_invitation_fn: Annotated[
        RevokeOwnerInvitationFn,
        Depends(staff_dependencies.provide_revoke_owner_invitation_fn),
    ],
) -> RevokeOwnerInvitationResponse:
    await use_cases.revoke_owner_invitation(invitation_id, revoke_owner_invitation_fn)
    return RevokeOwnerInvitationResponse(detail="Invitation revoked")

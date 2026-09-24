from src.core.cryptography.ports import EncryptionService

from .domain import Invitation
from .schemas import InvitationResponse


def domain_to_invitation_response(
    invitation: Invitation, encryption_service: EncryptionService
) -> InvitationResponse:
    return InvitationResponse(
        id=invitation.id,
        email=encryption_service.decrypt(invitation.encrypted_email),
        role=invitation.role,
        expires_at=invitation.expires_at,
        invited_by=invitation.invited_by,
        created_at=invitation.created_at,
    )

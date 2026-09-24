from src.invitations.domain import Invitation, InvitationCreate
from src.users.domain import Role

from .models import InvitationRow


def row_to_domain(row: InvitationRow) -> Invitation:
    return Invitation(
        id=row.id,
        organization_id=row.organization_id,
        encrypted_email=row.email,
        email_hash=row.email_hash,
        role=Role(row.role),
        expires_at=row.expires_at,
        accepted_at=row.accepted_at,
        revoked_at=row.revoked_at,
        invited_by=row.invited_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def domain_create_to_row(invitation: InvitationCreate) -> InvitationRow:
    return InvitationRow(
        organization_id=invitation.organization_id,
        email=invitation.encrypted_email,
        email_hash=invitation.email_hash,
        role=invitation.role,
        token_hash=invitation.token_hash,
        expires_at=invitation.expires_at,
        invited_by=invitation.invited_by,
    )

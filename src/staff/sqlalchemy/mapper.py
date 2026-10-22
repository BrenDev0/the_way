from src.staff.domain import (
    OwnerInvitation,
    OwnerInvitationCreate,
    StaffMember,
    StaffMemberCreate,
    StaffSession,
    StaffSessionCreate,
)

from .models import OwnerInvitationRow, StaffMemberRow, StaffSessionRow


def member_to_domain(row: StaffMemberRow) -> StaffMember:
    return StaffMember(
        id=row.id,
        encrypted_email=row.email,
        email_hash=row.email_hash,
        password_hash=row.password,
        created_at=row.created_at,
    )


def member_create_to_row(member: StaffMemberCreate) -> StaffMemberRow:
    return StaffMemberRow(
        email=member.encrypted_email,
        email_hash=member.email_hash,
        password=member.password_hash,
    )


def session_to_domain(row: StaffSessionRow) -> StaffSession:
    return StaffSession(
        id=row.id,
        staff_id=row.staff_id,
        token_hash=row.token_hash,
        expires_at=row.expires_at,
        last_seen_at=row.last_seen_at,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
    )


def session_create_to_row(session: StaffSessionCreate) -> StaffSessionRow:
    return StaffSessionRow(
        staff_id=session.staff_id,
        token_hash=session.token_hash,
        expires_at=session.expires_at,
        last_seen_at=session.last_seen_at,
    )


def invitation_to_domain(row: OwnerInvitationRow) -> OwnerInvitation:
    return OwnerInvitation(
        id=row.id,
        organization_name=row.organization_name,
        encrypted_email=row.email,
        email_hash=row.email_hash,
        seat_limit=row.seat_limit,
        expires_at=row.expires_at,
        accepted_at=row.accepted_at,
        revoked_at=row.revoked_at,
        invited_by=row.invited_by,
        organization_id=row.organization_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def invitation_create_to_row(invitation: OwnerInvitationCreate) -> OwnerInvitationRow:
    return OwnerInvitationRow(
        organization_name=invitation.organization_name,
        email=invitation.encrypted_email,
        email_hash=invitation.email_hash,
        seat_limit=invitation.seat_limit,
        token_hash=invitation.token_hash,
        expires_at=invitation.expires_at,
        invited_by=invitation.invited_by,
    )

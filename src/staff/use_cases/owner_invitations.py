from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from src.core.communications.ports import EmailSender
from src.core.cryptography.ports import EncryptionService, HashingService
from src.core.exceptions import ConflictError, NotFoundError, ValidationError
from src.organizations.domain import Organization, OrganizationCreate
from src.organizations.ports import CreateOrganizationFn
from src.staff import emails as staff_emails
from src.staff import tokens
from src.staff.domain import (
    OwnerInvitation,
    OwnerInvitationCreate,
    OwnerInvitationStatus,
    StaffMember,
    status_of,
)
from src.staff.ports import (
    ClaimOwnerInvitationFn,
    CreateOwnerInvitationFn,
    DeleteOwnerInvitationFn,
    GetOwnerInvitationByTokenHashFn,
    GetOwnerInvitationFn,
    ListOwnerInvitationsFn,
    RevokeOwnerInvitationFn,
    RevokePendingOwnerInvitationsForEmailFn,
)
from src.users.domain import Role, User, UserCreate
from src.users.ports import CreateUserFn, GetUserByEmailHashFn

MAX_ORGANIZATION_NAME_LENGTH = 255


def _invalid_token() -> NotFoundError:
    return NotFoundError(message="That invitation link is not valid", code="invitation_invalid")


def _already_has_account() -> ConflictError:
    return ConflictError(
        message="Someone with this email already has an account",
        code="user_email_already_exists",
    )


async def invite_owner(
    staff: StaffMember,
    organization_name: str,
    email: str,
    seat_limit: int | None,
    get_user_by_email_hash_fn: GetUserByEmailHashFn,
    revoke_pending_for_email_fn: RevokePendingOwnerInvitationsForEmailFn,
    create_owner_invitation_fn: CreateOwnerInvitationFn,
    email_sender: EmailSender,
    hashing_service: HashingService,
    encryption_service: EncryptionService,
    accept_url: str,
) -> OwnerInvitation:
    """Invite someone to start an organization as its owner. Nothing is created yet but
    the invitation: the organization and the account appear when it is accepted."""
    organization_name = " ".join(organization_name.split())
    if not organization_name:
        raise ValidationError(message="The organization needs a name", code="organization_name_required")
    if len(organization_name) > MAX_ORGANIZATION_NAME_LENGTH:
        raise ValidationError(message="That organization name is too long", code="organization_name_too_long")
    if seat_limit is not None and seat_limit < 1:
        raise ValidationError(message="Seats must be at least 1", code="seat_limit_invalid")

    email = email.strip()
    if "@" not in email:
        raise ValidationError(message="That is not an email address", code="invitation_email_invalid")

    email_hash = hashing_service.deterministic_hash(email)
    if await get_user_by_email_hash_fn(email_hash) is not None:
        raise _already_has_account()

    # Inviting the same address again replaces the earlier link, which stops working.
    await revoke_pending_for_email_fn(email_hash)

    raw_token = tokens.generate_token()
    invitation = await create_owner_invitation_fn(
        OwnerInvitationCreate(
            organization_name=organization_name,
            encrypted_email=encryption_service.encrypt(email),
            email_hash=email_hash,
            seat_limit=seat_limit,
            token_hash=hashing_service.deterministic_hash(raw_token),
            expires_at=tokens.build_expiration(),
            invited_by=staff.id,
        )
    )

    await email_sender.send(
        staff_emails.create_owner_invitation_email(
            link=f"{accept_url.rstrip('/')}?token={raw_token}",
            recipient_email=email,
            organization_name=organization_name,
        )
    )
    return invitation


async def list_owner_invitations(
    list_owner_invitations_fn: ListOwnerInvitationsFn,
) -> Sequence[OwnerInvitation]:
    """Every invitation we have sent, newest first -- pending, accepted, revoked and
    lapsed alike; the caller reads each one's status with `status_of`."""
    return await list_owner_invitations_fn()


async def revoke_owner_invitation(
    invitation_id: UUID,
    revoke_owner_invitation_fn: RevokeOwnerInvitationFn,
) -> None:
    if not await revoke_owner_invitation_fn(invitation_id):
        raise NotFoundError(message="Invitation not found", code="invitation_not_found")


async def delete_owner_invitation(
    invitation_id: UUID,
    get_owner_invitation_fn: GetOwnerInvitationFn,
    delete_owner_invitation_fn: DeleteOwnerInvitationFn,
) -> None:
    """Takes an invitation off the list for good -- one that has done its job and nobody needs to
    see: revoked, lapsed, or accepted for an organization that has since been deleted. One that
    could still be used (pending), or whose organization still exists (accepted), is the record
    of how something came to be: it is revoked, or the organization deleted, first."""
    invitation = await get_owner_invitation_fn(invitation_id)
    if invitation is None:
        raise NotFoundError(message="Invitation not found", code="invitation_not_found")

    if status_of(invitation, datetime.now(UTC)) in (OwnerInvitationStatus.PENDING, OwnerInvitationStatus.ACCEPTED):
        raise ConflictError(
            message="This invitation is still in use: revoke it, or delete its organization, first",
            code="owner_invitation_in_use",
        )

    await delete_owner_invitation_fn(invitation_id)


async def resolve_owner_invitation(
    token: str,
    get_owner_invitation_by_token_hash_fn: GetOwnerInvitationByTokenHashFn,
    hashing_service: HashingService,
) -> OwnerInvitation:
    invitation = await get_owner_invitation_by_token_hash_fn(hashing_service.deterministic_hash(token))
    if invitation is None:
        raise _invalid_token()

    if invitation.accepted_at is not None:
        raise ConflictError(
            message="That invitation has already been used",
            code="invitation_already_accepted",
        )

    if invitation.revoked_at is not None:
        raise _invalid_token()

    if tokens.ensure_aware_utc(invitation.expires_at) <= datetime.now(UTC):
        raise ValidationError(
            message="That invitation has expired. Ask for a new one.",
            code="invitation_expired",
        )

    return invitation


async def accept_owner_invitation(
    invitation: OwnerInvitation,
    password: str,
    get_user_by_email_hash_fn: GetUserByEmailHashFn,
    create_organization_fn: CreateOrganizationFn,
    claim_owner_invitation_fn: ClaimOwnerInvitationFn,
    create_user_fn: CreateUserFn,
    hashing_service: HashingService,
) -> tuple[Organization, User]:
    """Create the organization and its owner together. All in one transaction: if the
    link was taken by someone else a moment ago, the claim fails and the organization
    created here is rolled back with the request."""
    if await get_user_by_email_hash_fn(invitation.email_hash) is not None:
        raise _already_has_account()

    organization = await create_organization_fn(
        OrganizationCreate(name=invitation.organization_name, seat_limit=invitation.seat_limit)
    )

    if not await claim_owner_invitation_fn(invitation.id, organization.id):
        raise ConflictError(
            message="That invitation has already been used",
            code="invitation_already_accepted",
        )

    user = await create_user_fn(
        UserCreate(
            organization_id=organization.id,
            encrypted_email=invitation.encrypted_email,
            email_hash=invitation.email_hash,
            password_hash=hashing_service.hash_password(password),
            role=Role.OWNER,
        )
    )
    return organization, user

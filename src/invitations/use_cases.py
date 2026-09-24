from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from src.core.communications import service as communications_service
from src.core.communications.ports import EmailSender
from src.core.cryptography.ports import EncryptionService, HashingService
from src.core.exceptions import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from src.organizations.domain import Organization
from src.users.domain import Role, User, UserCreate
from src.users.ports import (
    CountUsersForOrganizationFn,
    CreateUserFn,
    GetUserByEmailHashFn,
)

from . import tokens
from .domain import INVITABLE_BY, Invitation, InvitationCreate
from .ports import (
    AcceptInvitationFn,
    CountPendingForOrganizationFn,
    CreateInvitationFn,
    GetInvitationByTokenHashFn,
    ListPendingForOrganizationFn,
    RevokeInvitationFn,
    RevokePendingForEmailFn,
)


def _not_found() -> NotFoundError:
    return NotFoundError(message="Invitation not found", code="invitation_not_found")


def _invalid_token() -> NotFoundError:
    return NotFoundError(
        message="That invitation link is not valid",
        code="invitation_invalid",
    )


def assert_may_invite(inviter_role: Role, invited_role: Role) -> None:
    allowed = INVITABLE_BY.get(inviter_role, ())
    if invited_role in allowed:
        return

    raise AuthorizationError(
        message=f"A {inviter_role} cannot invite a {invited_role}",
        code="invitation_role_not_allowed",
    )


def assert_seat_available(
    organization: Organization, members: int, pending: int
) -> None:
    if organization.seat_limit is None:
        return

    if members + pending >= organization.seat_limit:
        raise ConflictError(
            message=(
                f"This organization is using all {organization.seat_limit} of its seats. "
                "Revoke a pending invitation or remove a member first."
            ),
            code="organization_seat_limit_reached",
        )


async def invite_user(
    organization: Organization,
    inviter: User,
    email: str,
    role: Role,
    get_user_by_email_hash_fn: GetUserByEmailHashFn,
    count_users_for_organization_fn: CountUsersForOrganizationFn,
    count_pending_for_organization_fn: CountPendingForOrganizationFn,
    revoke_pending_for_email_fn: RevokePendingForEmailFn,
    create_invitation_fn: CreateInvitationFn,
    email_sender: EmailSender,
    hashing_service: HashingService,
    encryption_service: EncryptionService,
    accept_url: str,
) -> Invitation:
    assert_may_invite(inviter.role, role)

    email_hash = hashing_service.deterministic_hash(email)
    if await get_user_by_email_hash_fn(email_hash) is not None:
        raise ConflictError(
            message="Someone with this email already has an account",
            code="user_email_already_exists",
        )

    members = await count_users_for_organization_fn(organization.id)
    pending = await count_pending_for_organization_fn(organization.id)
    assert_seat_available(organization, members, pending)

    await revoke_pending_for_email_fn(organization.id, email_hash)

    raw_token = tokens.generate_token()
    invitation = await create_invitation_fn(
        InvitationCreate(
            organization_id=organization.id,
            encrypted_email=encryption_service.encrypt(email),
            email_hash=email_hash,
            role=role,
            token_hash=hashing_service.deterministic_hash(raw_token),
            expires_at=tokens.build_expiration(),
            invited_by=inviter.id,
        )
    )

    await email_sender.send(
        communications_service.create_invitation_email(
            link=f"{accept_url.rstrip('/')}?token={raw_token}",
            recipient_email=email,
            organization_name=organization.name,
            role=str(role),
        )
    )

    return invitation


async def list_invitations(
    organization_id: UUID,
    list_pending_for_organization_fn: ListPendingForOrganizationFn,
) -> Sequence[Invitation]:
    return await list_pending_for_organization_fn(organization_id)


async def revoke_invitation(
    invitation_id: UUID,
    organization_id: UUID,
    revoke_invitation_fn: RevokeInvitationFn,
) -> None:
    if not await revoke_invitation_fn(invitation_id, organization_id):
        raise _not_found()


async def accept_invitation(
    token: str,
    password: str,
    organization: Organization,
    invitation: Invitation,
    get_user_by_email_hash_fn: GetUserByEmailHashFn,
    count_users_for_organization_fn: CountUsersForOrganizationFn,
    count_pending_for_organization_fn: CountPendingForOrganizationFn,
    create_user_fn: CreateUserFn,
    accept_invitation_fn: AcceptInvitationFn,
    hashing_service: HashingService,
) -> User:
    if await get_user_by_email_hash_fn(invitation.email_hash) is not None:
        raise ConflictError(
            message="Someone with this email already has an account",
            code="user_email_already_exists",
        )

    members = await count_users_for_organization_fn(organization.id)
    pending = await count_pending_for_organization_fn(organization.id)
    assert_seat_available(organization, members, pending - 1)

    user = await create_user_fn(
        UserCreate(
            organization_id=invitation.organization_id,
            encrypted_email=invitation.encrypted_email,
            email_hash=invitation.email_hash,
            password_hash=hashing_service.hash_password(password),
            role=invitation.role,
        )
    )
    await accept_invitation_fn(invitation.id)
    return user


async def resolve_invitation(
    token: str,
    get_invitation_by_token_hash_fn: GetInvitationByTokenHashFn,
    hashing_service: HashingService,
) -> Invitation:
    invitation = await get_invitation_by_token_hash_fn(
        hashing_service.deterministic_hash(token)
    )
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

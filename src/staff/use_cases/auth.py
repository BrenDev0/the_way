from datetime import UTC, datetime

from src.core.cryptography.ports import EncryptionService, HashingService
from src.core.exceptions import AuthenticationError, ConflictError, ValidationError
from src.sessions.tokens import SessionTokenService
from src.staff import config
from src.staff.domain import (
    StaffMember,
    StaffMemberCreate,
    StaffSession,
    StaffSessionCreate,
)
from src.staff.ports import (
    CreateStaffMemberFn,
    CreateStaffSessionFn,
    GetStaffMemberByEmailHashFn,
    GetStaffMemberByIdFn,
    GetStaffSessionByTokenHashFn,
    RevokeStaffSessionByTokenHashFn,
    TouchStaffSessionFn,
)
from src.staff.tokens import ensure_aware_utc


def invalid_credentials() -> AuthenticationError:
    return AuthenticationError(message="Incorrect email or password", code="invalid_credentials")


async def login_staff(
    email: str,
    password: str,
    get_staff_member_by_email_hash_fn: GetStaffMemberByEmailHashFn,
    hashing_service: HashingService,
    create_staff_session_fn: CreateStaffSessionFn,
    token_service: SessionTokenService,
) -> tuple[StaffMember, str]:
    """Sign a staff member in: the raw session token, to be set as a cookie. An unknown
    email still pays for a password hash, so the response time does not reveal which
    emails belong to staff."""
    staff = await get_staff_member_by_email_hash_fn(hashing_service.deterministic_hash(email.strip()))
    if staff is None:
        hashing_service.hash_password(password)
        raise invalid_credentials()
    if not hashing_service.compare_password(password, staff.password_hash):
        raise invalid_credentials()

    raw_token = token_service.generate_session_token()
    now = datetime.now(UTC)
    await create_staff_session_fn(
        StaffSessionCreate(
            staff_id=staff.id,
            token_hash=token_service.hash_session_token(raw_token),
            expires_at=token_service.build_expiration(now),
            last_seen_at=now,
        )
    )
    return staff, raw_token


async def resolve_staff_session(
    token: str,
    get_staff_session_by_token_hash_fn: GetStaffSessionByTokenHashFn,
    touch_staff_session_fn: TouchStaffSessionFn,
    token_service: SessionTokenService,
) -> StaffSession | None:
    session = await get_staff_session_by_token_hash_fn(token_service.hash_session_token(token))
    if session is None or session.revoked_at is not None:
        return None
    if ensure_aware_utc(session.expires_at) <= datetime.now(UTC):
        return None
    return await touch_staff_session_fn(session.id) or session


async def get_staff_member(
    session: StaffSession,
    get_staff_member_by_id_fn: GetStaffMemberByIdFn,
) -> StaffMember:
    staff = await get_staff_member_by_id_fn(session.staff_id)
    if staff is None:
        raise AuthenticationError(message="Invalid session", code="invalid_session")
    return staff


async def logout_staff(
    token: str,
    revoke_staff_session_by_token_hash_fn: RevokeStaffSessionByTokenHashFn,
    token_service: SessionTokenService,
) -> None:
    if not await revoke_staff_session_by_token_hash_fn(token_service.hash_session_token(token)):
        raise AuthenticationError(message="Session not found", code="session_not_found")


async def create_staff_member(
    email: str,
    password: str,
    get_staff_member_by_email_hash_fn: GetStaffMemberByEmailHashFn,
    create_staff_member_fn: CreateStaffMemberFn,
    hashing_service: HashingService,
    encryption_service: EncryptionService,
) -> StaffMember:
    """Add someone to Xplorers' staff. There is no route for this: it is run from a
    command (src/staff/create.py) by a person with access to the server."""
    email = email.strip()
    if "@" not in email:
        raise ValidationError(message="That is not an email address", code="staff_email_invalid")
    if len(password) < config.MIN_STAFF_PASSWORD_LENGTH:
        raise ValidationError(
            message=f"The password must be at least {config.MIN_STAFF_PASSWORD_LENGTH} characters",
            code="staff_password_too_short",
        )

    email_hash = hashing_service.deterministic_hash(email)
    if await get_staff_member_by_email_hash_fn(email_hash) is not None:
        raise ConflictError(message="That person is already on the staff", code="staff_email_already_exists")

    return await create_staff_member_fn(
        StaffMemberCreate(
            encrypted_email=encryption_service.encrypt(email),
            email_hash=email_hash,
            password_hash=hashing_service.hash_password(password),
        )
    )

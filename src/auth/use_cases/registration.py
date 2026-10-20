from datetime import datetime

from src.auth import emails as auth_emails
from src.auth import service as auth_service
from src.core.cache.ports import CacheStore
from src.core.communications.ports import EmailSender
from src.core.cryptography.ports import EncryptionService, HashingService
from src.core.exceptions import ConflictError
from src.organizations.domain import OrganizationCreate
from src.organizations.ports import CreateOrganizationFn
from src.users.domain import Role, User, UserCreate
from src.users.ports import CreateUserFn, GetUserByEmailHashFn


async def send_registration_verification_code(
    email: str,
    cache_store: CacheStore,
    hashing_service: HashingService,
    get_user_by_email_hash_fn: GetUserByEmailHashFn,
    email_sender: EmailSender,
) -> datetime:
    email_hash = hashing_service.deterministic_hash(email)
    existing_user = await get_user_by_email_hash_fn(email_hash)
    if existing_user is not None:
        raise ConflictError(
            message="User with this email already exists",
            code="user_email_already_exists",
        )

    raw_code, expires_at = await auth_service.issue_registration_verification_code(
        email_hash=email_hash,
        cache_store=cache_store,
        code_hash_fn=hashing_service.deterministic_hash,
    )
    await email_sender.send(auth_emails.create_verification_email(raw_code, email))
    return expires_at


async def register_user(
    organization_name: str,
    email: str,
    password: str,
    verification_code: str,
    create_organization_fn: CreateOrganizationFn,
    create_user_fn: CreateUserFn,
    get_user_by_email_hash_fn: GetUserByEmailHashFn,
    cache_store: CacheStore,
    hashing_service: HashingService,
    encryption_service: EncryptionService,
) -> User:
    email_hash = hashing_service.deterministic_hash(email)
    existing_user = await get_user_by_email_hash_fn(email_hash)
    if existing_user is not None:
        raise ConflictError(
            message="User with this email already exists",
            code="user_email_already_exists",
        )

    await auth_service.verify_registration_email_code(
        email_hash=email_hash,
        submitted_code=verification_code,
        cache_store=cache_store,
        compare_code_hash_fn=lambda raw_code, stored_code_hash: hashing_service.deterministic_hash(raw_code)
        == stored_code_hash,
    )

    organization = await create_organization_fn(OrganizationCreate(name=organization_name))

    encrypted_email = encryption_service.encrypt(email)
    password_hash = hashing_service.hash_password(password)
    user_to_create = UserCreate(
        organization_id=organization.id,
        encrypted_email=encrypted_email,
        email_hash=email_hash,
        password_hash=password_hash,
        role=Role.OWNER,
    )
    return await create_user_fn(user_to_create)

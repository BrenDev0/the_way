import pytest
from helpers import make_organization, make_session, make_user

from src.auth import use_cases as auth_use_cases
from src.auth.cache import AuthCacheKey, build_auth_cache_key
from src.core.communications.domain import Email
from src.core.exceptions import AuthenticationError, ConflictError
from src.core.sessions.domain import SessionCreate
from src.core.sessions.tokens import SessionTokenService
from src.organizations.domain import OrganizationCreate
from src.users.domain import UserCreate

EMAIL = "founder@example.com"
PASSWORD = "hunter2"


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[Email] = []

    async def send(self, email: Email) -> None:
        self.sent.append(email)


async def no_user(email_hash: str):
    return None


async def existing_user(email_hash: str):
    return make_user()


def seed_valid_code(cache_store, hashing_service, code: str = "123456"):
    email_hash = hashing_service.deterministic_hash(EMAIL)
    code_key = build_auth_cache_key(AuthCacheKey.VERIFICATION_CODE, email_hash)
    cache_store.data[code_key] = hashing_service.deterministic_hash(code)


@pytest.fixture
def sender():
    return FakeEmailSender()


@pytest.fixture
def created_orgs():
    return []


@pytest.fixture
def created_users():
    return []


@pytest.fixture
def register(created_orgs, created_users, cache_store, hashing_service, encryption_service):
    async def create_org(organization: OrganizationCreate):
        created_orgs.append(organization)
        return make_organization(name=organization.name)

    async def create_user(user: UserCreate):
        created_users.append(user)
        return make_user(
            organization_id=user.organization_id,
            encrypted_email=user.encrypted_email,
            email_hash=user.email_hash,
            password_hash=user.password_hash,
            role=user.role,
        )

    async def run(code="123456", get_user_by_email_hash_fn=no_user):
        return await auth_use_cases.register_user(
            organization_name="Acme Inc",
            email=EMAIL,
            password=PASSWORD,
            verification_code=code,
            create_organization_fn=create_org,
            create_user_fn=create_user,
            get_user_by_email_hash_fn=get_user_by_email_hash_fn,
            cache_store=cache_store,
            hashing_service=hashing_service,
            encryption_service=encryption_service,
        )

    return run


@pytest.fixture
def login(hashing_service):
    async def run(user, password=PASSWORD):
        async def get_user(email_hash: str):
            return user

        async def create_session_fn(session_create: SessionCreate):
            return make_session(user_id=session_create.user_id)

        return await auth_use_cases.login_user(
            email=EMAIL,
            password=password,
            get_user_by_email_hash_fn=get_user,
            hashing_service=hashing_service,
            create_session_fn=create_session_fn,
            session_token_service=SessionTokenService(),
        )

    return run


async def test_send_verification_sends_an_email_to_the_requester(
    cache_store, hashing_service, sender
):
    await auth_use_cases.send_registration_verification_code(
        email=EMAIL,
        cache_store=cache_store,
        hashing_service=hashing_service,
        get_user_by_email_hash_fn=no_user,
        email_sender=sender,
    )

    assert len(sender.sent) == 1
    assert sender.sent[0].recipient == EMAIL


async def test_send_verification_rejects_an_existing_email_before_sending(
    cache_store, hashing_service, sender
):
    with pytest.raises(ConflictError) as exc:
        await auth_use_cases.send_registration_verification_code(
            email=EMAIL,
            cache_store=cache_store,
            hashing_service=hashing_service,
            get_user_by_email_hash_fn=existing_user,
            email_sender=sender,
        )

    assert exc.value.code == "user_email_already_exists"
    assert sender.sent == []


async def test_register_creates_org_then_binds_user_to_it(
    register, created_orgs, created_users, cache_store, hashing_service
):
    seed_valid_code(cache_store, hashing_service)

    user = await register()

    assert [o.name for o in created_orgs] == ["Acme Inc"]
    assert len(created_users) == 1
    assert user.organization_id is not None
    assert created_users[0].organization_id == user.organization_id


async def test_register_stores_the_email_encrypted(
    register, created_users, cache_store, hashing_service, encryption_service
):
    seed_valid_code(cache_store, hashing_service)

    user = await register()

    assert created_users[0].encrypted_email == encryption_service.encrypt(EMAIL)
    assert user.encrypted_email == encryption_service.encrypt(EMAIL)


async def test_register_hashes_the_password(
    register, created_users, cache_store, hashing_service
):
    seed_valid_code(cache_store, hashing_service)

    await register()

    assert created_users[0].password_hash == hashing_service.hash_password(PASSWORD)
    assert created_users[0].password_hash != PASSWORD


async def test_register_rejects_an_existing_email_before_creating_anything(
    register, created_orgs, created_users
):
    with pytest.raises(ConflictError) as exc:
        await register(get_user_by_email_hash_fn=existing_user)

    assert exc.value.code == "user_email_already_exists"
    assert created_orgs == []
    assert created_users == []


async def test_register_creates_no_org_for_a_bad_verification_code(
    register, created_orgs, created_users, cache_store, hashing_service
):
    seed_valid_code(cache_store, hashing_service, code="123456")

    with pytest.raises(AuthenticationError):
        await register(code="000000")

    assert created_orgs == []
    assert created_users == []


async def test_login_returns_the_user_and_a_session_token(login, hashing_service):
    user = make_user(password_hash=hashing_service.hash_password(PASSWORD))

    returned, token = await login(user)

    assert returned is user
    assert token


async def test_login_rejects_an_unknown_email(login):
    with pytest.raises(AuthenticationError) as exc:
        await login(None)

    assert exc.value.code == "invalid_credentials"


async def test_login_rejects_a_wrong_password(login, hashing_service):
    user = make_user(password_hash=hashing_service.hash_password(PASSWORD))

    with pytest.raises(AuthenticationError) as exc:
        await login(user, password="wrong")

    assert exc.value.code == "invalid_credentials"


async def test_login_unknown_email_and_wrong_password_look_identical(login, hashing_service):
    user = make_user(password_hash=hashing_service.hash_password(PASSWORD))

    with pytest.raises(AuthenticationError) as unknown:
        await login(None)
    with pytest.raises(AuthenticationError) as wrong:
        await login(user, password="wrong")

    assert unknown.value.code == wrong.value.code
    assert unknown.value.message == wrong.value.message


async def test_logout_revokes_the_session():
    revoked: list[str] = []

    async def revoke_fn(token_hash: str):
        revoked.append(token_hash)
        return True

    await auth_use_cases.logout_user(
        session_token="raw-token",
        revoke_session_by_token_hash_fn=revoke_fn,
        session_token_service=SessionTokenService(),
    )

    assert len(revoked) == 1


async def test_logout_rejects_an_unknown_session():
    async def revoke_fn(token_hash: str):
        return False

    with pytest.raises(AuthenticationError) as exc:
        await auth_use_cases.logout_user(
            session_token="raw-token",
            revoke_session_by_token_hash_fn=revoke_fn,
            session_token_service=SessionTokenService(),
        )

    assert exc.value.code == "session_not_found"

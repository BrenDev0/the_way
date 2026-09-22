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


def seed_valid_code(cache_store, hashing_service, code: str = "123456"):
    email_hash = hashing_service.deterministic_hash(EMAIL)
    code_key = build_auth_cache_key(AuthCacheKey.VERIFICATION_CODE, email_hash)
    cache_store.data[code_key] = hashing_service.deterministic_hash(code)


class TestSendRegistrationVerificationCode:
    async def test_sends_an_email_to_the_requester(self, cache_store, hashing_service):
        sender = FakeEmailSender()

        await auth_use_cases.send_registration_verification_code(
            email=EMAIL,
            cache_store=cache_store,
            hashing_service=hashing_service,
            get_user_by_email_hash_fn=no_user,
            email_sender=sender,
        )

        assert len(sender.sent) == 1
        assert sender.sent[0].recipient == EMAIL

    async def test_existing_email_is_rejected_before_sending(self, cache_store, hashing_service):
        sender = FakeEmailSender()

        async def existing_user(email_hash: str):
            return make_user()

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


class TestRegisterUser:
    def setup_method(self):
        self.orgs: list[OrganizationCreate] = []
        self.users: list[UserCreate] = []

    async def create_org(self, organization: OrganizationCreate):
        self.orgs.append(organization)
        return make_organization(name=organization.name)

    async def create_user(self, user: UserCreate):
        self.users.append(user)
        return make_user(
            organization_id=user.organization_id,
            encrypted_email=user.encrypted_email,
            email_hash=user.email_hash,
            password_hash=user.password_hash,
        )

    async def _register(self, cache_store, hashing_service, encryption_service, code="123456"):
        return await auth_use_cases.register_user(
            organization_name="Acme Inc",
            email=EMAIL,
            password=PASSWORD,
            verification_code=code,
            create_organization_fn=self.create_org,
            create_user_fn=self.create_user,
            get_user_by_email_hash_fn=no_user,
            cache_store=cache_store,
            hashing_service=hashing_service,
            encryption_service=encryption_service,
        )

    async def test_creates_org_then_binds_user_to_it(
        self, cache_store, hashing_service, encryption_service
    ):
        seed_valid_code(cache_store, hashing_service)

        user = await self._register(cache_store, hashing_service, encryption_service)

        assert [o.name for o in self.orgs] == ["Acme Inc"]
        assert len(self.users) == 1
        assert user.organization_id is not None
        assert self.users[0].organization_id == user.organization_id

    async def test_email_is_stored_encrypted(
        self, cache_store, hashing_service, encryption_service
    ):
        seed_valid_code(cache_store, hashing_service)

        user = await self._register(cache_store, hashing_service, encryption_service)

        assert self.users[0].encrypted_email == encryption_service.encrypt(EMAIL)
        assert user.encrypted_email == encryption_service.encrypt(EMAIL)

    async def test_password_is_hashed_not_stored_raw(
        self, cache_store, hashing_service, encryption_service
    ):
        seed_valid_code(cache_store, hashing_service)

        await self._register(cache_store, hashing_service, encryption_service)

        assert self.users[0].password_hash == hashing_service.hash_password(PASSWORD)
        assert self.users[0].password_hash != PASSWORD

    async def test_existing_email_is_rejected_before_creating_anything(
        self, cache_store, hashing_service, encryption_service
    ):
        async def existing_user(email_hash: str):
            return make_user()

        with pytest.raises(ConflictError) as exc:
            await auth_use_cases.register_user(
                organization_name="Acme Inc",
                email=EMAIL,
                password=PASSWORD,
                verification_code="123456",
                create_organization_fn=self.create_org,
                create_user_fn=self.create_user,
                get_user_by_email_hash_fn=existing_user,
                cache_store=cache_store,
                hashing_service=hashing_service,
                encryption_service=encryption_service,
            )

        assert exc.value.code == "user_email_already_exists"
        assert self.orgs == []
        assert self.users == []

    async def test_bad_verification_code_creates_no_org(
        self, cache_store, hashing_service, encryption_service
    ):
        seed_valid_code(cache_store, hashing_service, code="123456")

        with pytest.raises(AuthenticationError):
            await self._register(cache_store, hashing_service, encryption_service, code="000000")

        assert self.orgs == []
        assert self.users == []


class TestLoginUser:
    async def _login(self, user, hashing_service, password=PASSWORD):
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

    async def test_returns_the_user_and_a_session_token(self, hashing_service):
        user = make_user(password_hash=hashing_service.hash_password(PASSWORD))

        returned, token = await self._login(user, hashing_service)

        assert returned is user
        assert token

    async def test_unknown_email_is_rejected(self, hashing_service):
        with pytest.raises(AuthenticationError) as exc:
            await self._login(None, hashing_service)
        assert exc.value.code == "invalid_credentials"

    async def test_wrong_password_is_rejected(self, hashing_service):
        user = make_user(password_hash=hashing_service.hash_password(PASSWORD))

        with pytest.raises(AuthenticationError) as exc:
            await self._login(user, hashing_service, password="wrong")
        assert exc.value.code == "invalid_credentials"

    async def test_unknown_email_and_wrong_password_look_identical(self, hashing_service):
        user = make_user(password_hash=hashing_service.hash_password(PASSWORD))

        with pytest.raises(AuthenticationError) as unknown:
            await self._login(None, hashing_service)
        with pytest.raises(AuthenticationError) as wrong:
            await self._login(user, hashing_service, password="wrong")

        assert unknown.value.code == wrong.value.code
        assert unknown.value.message == wrong.value.message


class TestLogoutUser:
    async def test_revokes_the_session(self):
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

    async def test_unknown_session_is_rejected(self):
        async def revoke_fn(token_hash: str):
            return False

        with pytest.raises(AuthenticationError) as exc:
            await auth_use_cases.logout_user(
                session_token="raw-token",
                revoke_session_by_token_hash_fn=revoke_fn,
                session_token_service=SessionTokenService(),
            )
        assert exc.value.code == "session_not_found"

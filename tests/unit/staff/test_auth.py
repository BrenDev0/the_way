from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.core.exceptions import AuthenticationError, ConflictError, ValidationError
from src.sessions.tokens import SessionTokenService
from src.staff.domain import (
    StaffMember,
    StaffMemberCreate,
    StaffSession,
    StaffSessionCreate,
)
from src.staff.use_cases import auth as auth_use_cases

EMAIL = "someone@xplorers.example"
PASSWORD = "a-long-enough-password"


def make_staff(hashing_service, password: str = PASSWORD) -> StaffMember:
    return StaffMember(
        id=uuid4(),
        encrypted_email=f"enc::{EMAIL}",
        email_hash=f"dhash::{EMAIL}",
        password_hash=hashing_service.hash_password(password),
        created_at=datetime.now(UTC),
    )


def make_session(*, staff_id=None, expires_in=timedelta(hours=1), revoked_at=None) -> StaffSession:
    now = datetime.now(UTC)
    return StaffSession(
        id=uuid4(),
        staff_id=staff_id or uuid4(),
        token_hash="hash",
        expires_at=now + expires_in,
        last_seen_at=now,
        created_at=now,
        revoked_at=revoked_at,
    )


@pytest.fixture
def login(hashing_service):
    created: list[StaffSessionCreate] = []

    async def run(staff, password=PASSWORD):
        async def get_staff(email_hash: str):
            return staff

        async def create_session(session: StaffSessionCreate):
            created.append(session)
            return make_session(staff_id=session.staff_id)

        return await auth_use_cases.login_staff(
            email=EMAIL,
            password=password,
            get_staff_member_by_email_hash_fn=get_staff,
            hashing_service=hashing_service,
            create_staff_session_fn=create_session,
            token_service=SessionTokenService(),
        )

    run.created = created
    return run


async def test_login_returns_the_staff_member_and_a_session_token(login, hashing_service):
    staff = make_staff(hashing_service)

    returned, token = await login(staff)

    assert returned is staff
    assert token
    assert login.created[0].staff_id == staff.id


async def test_only_a_hash_of_the_token_is_stored(login, hashing_service):
    _, token = await login(make_staff(hashing_service))

    assert login.created[0].token_hash == SessionTokenService().hash_session_token(token)
    assert login.created[0].token_hash != token


async def test_the_session_expires_when_the_token_service_says(hashing_service):
    created: list[StaffSessionCreate] = []

    async def create_session(session: StaffSessionCreate):
        created.append(session)
        return make_session(staff_id=session.staff_id)

    async def get_staff(email_hash: str):
        return make_staff(hashing_service)

    await auth_use_cases.login_staff(
        email=EMAIL,
        password=PASSWORD,
        get_staff_member_by_email_hash_fn=get_staff,
        hashing_service=hashing_service,
        create_staff_session_fn=create_session,
        token_service=SessionTokenService(session_ttl=timedelta(hours=12)),
    )

    lifetime = created[0].expires_at - created[0].last_seen_at
    assert lifetime == timedelta(hours=12)


def test_staff_sessions_are_shorter_than_customers_and_have_their_own_cookie():
    from dataclasses import replace

    from src.sessions.config import SessionCookieConfig
    from src.staff import config
    from src.staff.fastapi import dependencies as staff_dependencies

    customers = SessionCookieConfig()

    staff_cookie = staff_dependencies.get_staff_cookie_config(customers)
    staff_tokens = staff_dependencies.get_staff_token_service()

    assert staff_cookie.name == config.STAFF_SESSION_COOKIE_NAME != customers.name
    assert staff_cookie.max_age_seconds == config.STAFF_SESSION_TTL_SECONDS < customers.max_age_seconds
    assert staff_tokens.session_ttl == timedelta(seconds=config.STAFF_SESSION_TTL_SECONDS)
    # everything else about the cookie follows the customers' settings
    assert replace(staff_cookie, name=customers.name, max_age_seconds=customers.max_age_seconds) == customers


async def test_login_rejects_an_unknown_email_and_a_wrong_password_alike(login, hashing_service):
    with pytest.raises(AuthenticationError) as unknown:
        await login(None)
    with pytest.raises(AuthenticationError) as wrong:
        await login(make_staff(hashing_service), password="wrong")

    assert unknown.value.code == wrong.value.code == "invalid_credentials"
    assert unknown.value.message == wrong.value.message
    assert login.created == []


async def resolve(session, token_service=None):
    touched: list = []

    async def get_session(token_hash: str):
        return session

    async def touch(session_id):
        touched.append(session_id)
        return None

    result = await auth_use_cases.resolve_staff_session(
        token="raw",
        get_staff_session_by_token_hash_fn=get_session,
        touch_staff_session_fn=touch,
        token_service=token_service or SessionTokenService(),
    )
    return result, touched


async def test_a_live_session_resolves_and_is_touched():
    session = make_session()

    result, touched = await resolve(session)

    assert result is session
    assert touched == [session.id]


@pytest.mark.parametrize(
    "session",
    [
        None,
        make_session(expires_in=timedelta(seconds=-1)),
        make_session(revoked_at=datetime.now(UTC)),
    ],
    ids=["unknown", "expired", "revoked"],
)
async def test_a_session_that_is_unknown_expired_or_revoked_does_not_resolve(session):
    result, touched = await resolve(session)

    assert result is None
    assert touched == []


async def test_logout_of_an_unknown_session_is_refused():
    async def revoke(token_hash: str):
        return False

    with pytest.raises(AuthenticationError):
        await auth_use_cases.logout_staff(
            token="raw",
            revoke_staff_session_by_token_hash_fn=revoke,
            token_service=SessionTokenService(),
        )


@pytest.fixture
def create_staff(hashing_service, encryption_service):
    created: list[StaffMemberCreate] = []

    async def create(member: StaffMemberCreate):
        created.append(member)
        return StaffMember(
            id=uuid4(),
            encrypted_email=member.encrypted_email,
            email_hash=member.email_hash,
            password_hash=member.password_hash,
            created_at=datetime.now(UTC),
        )

    async def run(email=EMAIL, password=PASSWORD, existing=None):
        async def get_staff(email_hash: str):
            return existing

        return await auth_use_cases.create_staff_member(
            email=email,
            password=password,
            get_staff_member_by_email_hash_fn=get_staff,
            create_staff_member_fn=create,
            hashing_service=hashing_service,
            encryption_service=encryption_service,
        )

    run.created = created
    return run


async def test_a_staff_member_is_stored_with_an_encrypted_email_and_a_hashed_password(create_staff):
    await create_staff(email=f"  {EMAIL}  ")

    assert create_staff.created[0].encrypted_email == f"enc::{EMAIL}"
    assert create_staff.created[0].email_hash == f"dhash::{EMAIL}"
    assert create_staff.created[0].password_hash == f"pwhash::{PASSWORD}"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"email": "nope"}, "staff_email_invalid"),
        ({"password": ""}, "staff_password_empty"),
        ({"password": "a" * 73}, "staff_password_too_long"),
        # 25 characters, but 100 bytes: what bcrypt counts is bytes
        ({"password": "😀" * 25}, "staff_password_too_long"),
    ],
)
async def test_bad_staff_input_is_refused(create_staff, overrides, code):
    with pytest.raises(ValidationError) as exc:
        await create_staff(**overrides)

    assert exc.value.code == code
    assert create_staff.created == []


@pytest.mark.parametrize(
    "password",
    [
        "a",
        "1234",
        "password",
        "short",
        "correct horse battery staple",
        "   leading and trailing spaces   ",
        "contraseña-ñandú-ü",
        "a" * 72,
        "😀" * 18,  # 72 bytes exactly
        "!@#$%^&*()_+{}|:<>?",
    ],
    ids=["one character", "digits", "a common word", "short", "a passphrase", "spaces kept",
         "accents", "72 bytes", "72 bytes of emoji", "symbols"],
)
async def test_a_staff_member_can_choose_any_password_bcrypt_can_hash(create_staff, password):
    await create_staff(password=password)

    assert create_staff.created[0].password_hash == f"pwhash::{password}"  # kept exactly as typed


async def test_the_password_is_not_trimmed_or_changed(create_staff):
    await create_staff(password="  spaced  ")

    assert create_staff.created[0].password_hash == "pwhash::  spaced  "


async def test_the_same_person_cannot_be_added_twice(create_staff, hashing_service):
    with pytest.raises(ConflictError) as exc:
        await create_staff(existing=make_staff(hashing_service))

    assert exc.value.code == "staff_email_already_exists"
    assert create_staff.created == []

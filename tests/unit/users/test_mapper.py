from datetime import UTC, datetime
from uuid import uuid4

from helpers import FakeEncryptionService, make_user

from src.users import mapper as users_mapper
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import mapper as users_sql_mapper
from src.users.sqlalchemy.models import UserRow


def test_user_response_mapper_decrypts_email_and_carries_identifiers():
    user = make_user(encrypted_email="enc::someone@example.com")

    response = users_mapper.domain_to_user_response(user, FakeEncryptionService())

    assert response.id == user.id
    assert response.organization_id == user.organization_id
    assert response.email == "someone@example.com"
    assert response.created_at == user.created_at


def test_user_response_mapper_encrypted_email_never_leaks_into_the_response():
    user = make_user(encrypted_email="enc::someone@example.com")
    response = users_mapper.domain_to_user_response(user, FakeEncryptionService())
    assert not response.email.startswith("enc::")


def test_user_sql_alchemy_mapper_row_to_domain_maps_renamed_columns():
    row = UserRow(
        id=uuid4(),
        organization_id=uuid4(),
        email="enc::a@example.com",
        email_hash="dhash::a@example.com",
        password="pwhash::secret",
        role=Role.OWNER,
    )
    row.created_at = datetime.now(UTC)

    user = users_sql_mapper.row_to_domain(row)

    assert user.id == row.id
    assert user.organization_id == row.organization_id
    assert user.encrypted_email == row.email
    assert user.email_hash == row.email_hash
    assert user.password_hash == row.password
    assert user.role is Role.OWNER


def test_user_sql_alchemy_mapper_domain_create_to_row_maps_renamed_columns():
    create = UserCreate(
        organization_id=uuid4(),
        encrypted_email="enc::a@example.com",
        email_hash="dhash::a@example.com",
        password_hash="pwhash::secret",
        role=Role.ADMIN,
    )

    row = users_sql_mapper.domain_create_to_row(create)

    assert row.organization_id == create.organization_id
    assert row.email == create.encrypted_email
    assert row.email_hash == create.email_hash
    assert row.password == create.password_hash
    assert row.role is Role.ADMIN


def test_user_sql_alchemy_mapper_round_trip_preserves_values():
    create = UserCreate(
        organization_id=uuid4(),
        encrypted_email="enc::a@example.com",
        email_hash="dhash::a@example.com",
        password_hash="pwhash::secret",
        role=Role.ADMIN,
    )
    row = users_sql_mapper.domain_create_to_row(create)
    row.id = uuid4()
    row.created_at = datetime.now(UTC)

    user = users_sql_mapper.row_to_domain(row)

    assert user.encrypted_email == create.encrypted_email
    assert user.email_hash == create.email_hash
    assert user.password_hash == create.password_hash
    assert user.role is create.role

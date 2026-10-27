from uuid import uuid4

from helpers import make_api_key

from src.api_keys.domain import Provider
from src.api_keys.sqlalchemy import mapper
from src.api_keys.sqlalchemy.models import ApiKeyRow


def test_the_row_stores_the_ciphertext_not_the_domain_field_names():
    columns = {column.name for column in ApiKeyRow.__table__.columns}

    assert "secret" in columns
    assert "account_id" in columns
    assert "encrypted_secret" not in columns


def test_a_key_belongs_to_the_organization_and_not_to_a_user():
    columns = {column.name for column in ApiKeyRow.__table__.columns}

    assert "organization_id" in columns
    assert "user_id" not in columns
    assert "issued_by" not in columns
    assert "set_by" in columns


def test_one_key_per_provider_and_organization_is_enforced_by_the_table():
    constraint = next(
        c for c in ApiKeyRow.__table__.constraints if c.name == "uq_api_key_organization_provider"
    )

    assert {column.name for column in constraint.columns} == {"organization_id", "provider"}


def test_the_tenancy_column_is_indexed():
    indexed = {column.name for column in ApiKeyRow.__table__.columns if column.index}

    assert "organization_id" in indexed


def test_a_row_round_trips_through_the_mapper():
    api_key = make_api_key(
        provider=Provider.GOHIGHLEVEL,
        encrypted_secret="enc::pit",
        encrypted_account_id="enc::loc-1",
        last_four="tsec",
        set_by=uuid4(),
    )
    row = mapper.domain_create_to_row(api_key)
    row.id = api_key.id
    row.created_at = api_key.created_at
    row.updated_at = api_key.updated_at

    restored = mapper.row_to_domain(row)

    assert restored == api_key


def test_the_mapper_reads_the_provider_back_as_an_enum():
    row = ApiKeyRow(
        organization_id=uuid4(),
        provider="openai",
        secret="enc::x",
        last_four="abcd",
        account_id=None,
        model=None,
        set_by=None,
    )
    row.id = uuid4()
    row.created_at = row.updated_at = make_api_key().created_at

    assert mapper.row_to_domain(row).provider is Provider.OPENAI

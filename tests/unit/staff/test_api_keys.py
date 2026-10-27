"""Setting an organization's provider keys from the staff side."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from helpers import make_api_key

from src.api_keys.domain import Provider
from src.core.exceptions import NotFoundError
from src.staff.domain import OrganizationSummary, StaffMember
from src.staff.use_cases import api_keys as use_cases


def make_staff() -> StaffMember:
    return StaffMember(
        id=uuid4(),
        encrypted_email="enc::ana@xplorers.example",
        email_hash="dhash::ana@xplorers.example",
        password_hash="pwhash::x",
        created_at=datetime.now(UTC),
    )


def existing(organization_id):
    async def get_organization_summary_fn(requested):
        if requested != organization_id:
            return None
        return OrganizationSummary(
            id=organization_id,
            name="Acme",
            seat_limit=5,
            created_at=datetime.now(UTC),
            members=1,
            pending_invitations=0,
            owner_encrypted_email=None,
            files=0,
            bytes=0,
            last_seen_at=None,
        )

    return get_organization_summary_fn


async def test_setting_a_key_records_the_staff_member_who_did_it(encryption_service):
    organization_id, staff = uuid4(), make_staff()
    stored = []

    async def upsert_api_key_fn(api_key):
        stored.append(api_key)
        return make_api_key(organization_id=organization_id, set_by=api_key.set_by)

    await use_cases.set_api_key(
        staff=staff,
        organization_id=organization_id,
        provider=Provider.OPENAI,
        secret="sk-openai-1234",
        account_id=None,
        model=None,
        get_organization_summary_fn=existing(organization_id),
        upsert_api_key_fn=upsert_api_key_fn,
        encryption_service=encryption_service,
    )

    assert stored[0].set_by == staff.id
    assert stored[0].organization_id == organization_id
    assert stored[0].encrypted_secret == "enc::sk-openai-1234"


async def test_an_organization_that_does_not_exist_is_not_found_and_nothing_is_stored(encryption_service):
    stored = []

    async def upsert_api_key_fn(api_key):
        stored.append(api_key)

    with pytest.raises(NotFoundError) as exc:
        await use_cases.set_api_key(
            staff=make_staff(),
            organization_id=uuid4(),
            provider=Provider.OPENAI,
            secret="sk-openai-1234",
            account_id=None,
            model=None,
            get_organization_summary_fn=existing(uuid4()),
            upsert_api_key_fn=upsert_api_key_fn,
            encryption_service=encryption_service,
        )

    assert exc.value.code == "organization_not_found"
    assert stored == []


async def test_listing_and_deleting_also_need_the_organization_to_exist():
    async def list_api_keys_fn(_organization_id):
        raise AssertionError("must not be reached")

    async def delete_api_key_fn(_organization_id, _provider):
        raise AssertionError("must not be reached")

    with pytest.raises(NotFoundError):
        await use_cases.list_api_keys(uuid4(), existing(uuid4()), list_api_keys_fn)
    with pytest.raises(NotFoundError):
        await use_cases.delete_api_key(uuid4(), Provider.OPENAI, existing(uuid4()), delete_api_key_fn)

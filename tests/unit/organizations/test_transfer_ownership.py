from uuid import uuid4

import pytest
from helpers import make_user

from src.core.exceptions import NotFoundError, ValidationError
from src.organizations import use_cases as organizations_use_cases
from src.users.domain import Role


@pytest.fixture
def organization_id():
    return uuid4()


@pytest.fixture
def owner(organization_id):
    return make_user(organization_id=organization_id, role=Role.OWNER)


@pytest.fixture
def role_changes():
    return []


@pytest.fixture
def transfer(organization_id, owner, role_changes, cache_store):
    async def update_role(user_id, role):
        role_changes.append((user_id, role))
        return make_user(user_id=user_id, organization_id=organization_id, role=role)

    async def run(target, new_owner_id=None):
        async def get_user(user_id):
            return target

        return await organizations_use_cases.transfer_ownership(
            organization_id=organization_id,
            current_owner_id=owner.id,
            new_owner_id=new_owner_id or (target.id if target else uuid4()),
            get_user_by_id_fn=get_user,
            update_user_role_fn=update_role,
            cache_store=cache_store,
        )

    return run


async def test_promotes_the_target_and_demotes_the_caller(
    transfer, organization_id, owner, role_changes
):
    target = make_user(organization_id=organization_id, role=Role.MEMBER)

    await transfer(target)

    assert role_changes == [(target.id, Role.OWNER), (owner.id, Role.ADMIN)]


async def test_organization_is_never_left_without_an_owner(
    transfer, organization_id, role_changes
):
    target = make_user(organization_id=organization_id, role=Role.ADMIN)

    await transfer(target)

    assert [uid for uid, role in role_changes if role is Role.OWNER] == [target.id]


async def test_a_user_from_another_organization_is_rejected(transfer, role_changes):
    outsider = make_user(organization_id=uuid4(), role=Role.MEMBER)

    with pytest.raises(NotFoundError) as exc:
        await transfer(outsider)

    assert exc.value.code == "user_not_found"
    assert role_changes == []


async def test_an_outsider_is_indistinguishable_from_a_missing_user(transfer):
    outsider = make_user(organization_id=uuid4(), role=Role.MEMBER)

    with pytest.raises(NotFoundError) as foreign:
        await transfer(outsider)
    with pytest.raises(NotFoundError) as missing:
        await transfer(None)

    assert foreign.value.code == missing.value.code
    assert foreign.value.message == missing.value.message


async def test_unknown_user_changes_nothing(transfer, role_changes):
    with pytest.raises(NotFoundError):
        await transfer(None)

    assert role_changes == []


async def test_transferring_to_yourself_is_rejected(transfer, owner, role_changes):
    with pytest.raises(ValidationError) as exc:
        await transfer(owner, new_owner_id=owner.id)

    assert exc.value.code == "already_organization_owner"
    assert role_changes == []

from uuid import uuid4

import pytest

from src.core.exceptions import ConflictError
from src.users import use_cases as users_use_cases
from src.users.domain import Role


@pytest.fixture
def user_id():
    return uuid4()


@pytest.fixture
def calls():
    return []


@pytest.fixture
def delete(user_id, calls, cache_store):
    async def revoke_sessions_fn(uid):
        assert uid == user_id
        calls.append("revoke")
        return 2

    async def delete_user_fn(uid):
        assert uid == user_id
        calls.append("delete")
        return True

    async def run(role):
        await users_use_cases.delete_user(
            user_id=user_id,
            role=role,
            delete_user_fn=delete_user_fn,
            revoke_sessions_by_user_id_fn=revoke_sessions_fn,
            cache_store=cache_store,
        )

    return run


@pytest.mark.parametrize("role", [Role.ADMIN, Role.MEMBER])
async def test_revokes_sessions_before_deleting_the_user(delete, calls, role):
    await delete(role)

    assert calls == ["revoke", "delete"]


async def test_owner_cannot_delete_their_own_account(delete):
    with pytest.raises(ConflictError) as exc:
        await delete(Role.OWNER)

    assert exc.value.code == "owner_must_transfer_ownership"
    assert exc.value.status_code == 409


async def test_blocked_owner_deletion_changes_nothing(delete, calls):
    with pytest.raises(ConflictError):
        await delete(Role.OWNER)

    assert calls == []


async def test_listing_asks_only_for_the_callers_organization():
    from helpers import make_user

    from src.users import use_cases as users_use_cases

    asked = []
    organization_id = uuid4()

    async def list_users_fn(org_id):
        asked.append(org_id)
        return [make_user(organization_id=org_id)]

    listed = await users_use_cases.list_users(
        organization_id=organization_id,
        list_users_fn=list_users_fn,
    )

    assert asked == [organization_id]
    assert [user.organization_id for user in listed] == [organization_id]

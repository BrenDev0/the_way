from uuid import uuid4

import pytest
from helpers import make_user

from src.core.exceptions import NotFoundError, ValidationError
from src.organizations import use_cases as organizations_use_cases
from src.users.domain import Role


class TestTransferOwnership:
    def setup_method(self):
        self.organization_id = uuid4()
        self.owner = make_user(organization_id=self.organization_id, role=Role.OWNER)
        self.role_changes: list[tuple] = []

    async def _update_role(self, user_id, role):
        self.role_changes.append((user_id, role))
        return make_user(user_id=user_id, organization_id=self.organization_id, role=role)

    async def _transfer(self, target, cache_store, new_owner_id=None):
        async def get_user(user_id):
            return target

        return await organizations_use_cases.transfer_ownership(
            organization_id=self.organization_id,
            current_owner_id=self.owner.id,
            new_owner_id=new_owner_id or (target.id if target else uuid4()),
            get_user_by_id_fn=get_user,
            update_user_role_fn=self._update_role,
            cache_store=cache_store,
        )

    async def test_promotes_the_target_and_demotes_the_caller(self, cache_store):
        target = make_user(organization_id=self.organization_id, role=Role.MEMBER)

        await self._transfer(target, cache_store)

        assert self.role_changes == [
            (target.id, Role.OWNER),
            (self.owner.id, Role.ADMIN),
        ]

    async def test_organization_is_never_left_without_an_owner(self, cache_store):
        target = make_user(organization_id=self.organization_id, role=Role.ADMIN)

        await self._transfer(target, cache_store)

        promotions = [uid for uid, role in self.role_changes if role is Role.OWNER]
        assert promotions == [target.id]

    async def test_a_user_from_another_organization_is_rejected(self, cache_store):
        outsider = make_user(organization_id=uuid4(), role=Role.MEMBER)

        with pytest.raises(NotFoundError) as exc:
            await self._transfer(outsider, cache_store)

        assert exc.value.code == "user_not_found"
        assert self.role_changes == []

    async def test_an_outsider_is_indistinguishable_from_a_missing_user(self, cache_store):
        outsider = make_user(organization_id=uuid4(), role=Role.MEMBER)

        with pytest.raises(NotFoundError) as foreign:
            await self._transfer(outsider, cache_store)
        with pytest.raises(NotFoundError) as missing:
            await self._transfer(None, cache_store)

        assert foreign.value.code == missing.value.code
        assert foreign.value.message == missing.value.message

    async def test_unknown_user_changes_nothing(self, cache_store):
        with pytest.raises(NotFoundError):
            await self._transfer(None, cache_store)
        assert self.role_changes == []

    async def test_transferring_to_yourself_is_rejected(self, cache_store):
        with pytest.raises(ValidationError) as exc:
            await self._transfer(self.owner, cache_store, new_owner_id=self.owner.id)

        assert exc.value.code == "already_organization_owner"
        assert self.role_changes == []

from uuid import uuid4

import pytest

from src.core.exceptions import ConflictError
from src.users import use_cases as users_use_cases
from src.users.domain import Role


class TestDeleteUser:
    def setup_method(self):
        self.calls: list[str] = []
        self.user_id = uuid4()

    async def _revoke(self, uid):
        assert uid == self.user_id
        self.calls.append("revoke")
        return 2

    async def _delete(self, uid):
        assert uid == self.user_id
        self.calls.append("delete")
        return True

    async def _delete_user(self, role, cache_store):
        await users_use_cases.delete_user(
            user_id=self.user_id,
            role=role,
            delete_user_fn=self._delete,
            revoke_sessions_by_user_id_fn=self._revoke,
            cache_store=cache_store,
        )

    @pytest.mark.parametrize("role", [Role.ADMIN, Role.MEMBER])
    async def test_revokes_sessions_before_deleting_the_user(self, role, cache_store):
        await self._delete_user(role, cache_store)

        assert self.calls == ["revoke", "delete"]

    async def test_owner_cannot_delete_their_own_account(self, cache_store):
        with pytest.raises(ConflictError) as exc:
            await self._delete_user(Role.OWNER, cache_store)

        assert exc.value.code == "owner_must_transfer_ownership"
        assert exc.value.status_code == 409

    async def test_blocked_owner_deletion_changes_nothing(self, cache_store):
        with pytest.raises(ConflictError):
            await self._delete_user(Role.OWNER, cache_store)

        assert self.calls == []

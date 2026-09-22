import pytest
from helpers import make_user

from src.auth.dependencies import require_role
from src.core.exceptions import AuthorizationError
from src.users.domain import Role


class TestRequireRole:
    async def test_allows_a_listed_role(self):
        dependency = require_role(Role.OWNER, Role.ADMIN)
        user = make_user(role=Role.ADMIN)

        assert await dependency(current_user=user) is user

    @pytest.mark.parametrize("role", [Role.ADMIN, Role.MEMBER])
    async def test_rejects_an_unlisted_role(self, role):
        dependency = require_role(Role.OWNER)

        with pytest.raises(AuthorizationError) as exc:
            await dependency(current_user=make_user(role=role))

        assert exc.value.code == "insufficient_role"
        assert exc.value.status_code == 403

    async def test_owner_passes_an_owner_only_gate(self):
        dependency = require_role(Role.OWNER)
        user = make_user(role=Role.OWNER)

        assert await dependency(current_user=user) is user

    async def test_an_empty_allow_list_rejects_everyone(self):
        dependency = require_role()

        for role in Role:
            with pytest.raises(AuthorizationError):
                await dependency(current_user=make_user(role=role))

from uuid import uuid4

import pytest

from src.core.exceptions import ValidationError
from src.organizations.sqlalchemy import adapter
from src.organizations.sqlalchemy.models import OrganizationRow


class TestUpdateFieldWhitelist:
    def test_immutable_columns_are_not_updatable(self):
        assert adapter.UPDATABLE_FIELDS.isdisjoint({"id", "created_at", "updated_at"})

    def test_whitelist_only_names_real_columns(self):
        columns = {c.name for c in OrganizationRow.__table__.columns}
        assert adapter.UPDATABLE_FIELDS <= columns

    async def test_unknown_field_is_rejected(self):
        with pytest.raises(ValidationError) as exc:
            await adapter.update_by_id(None, uuid4(), {"not_a_column": "x"})
        assert exc.value.code == "organization_field_not_updatable"

    @pytest.mark.parametrize("field", ["id", "created_at", "updated_at"])
    async def test_database_owned_columns_cannot_be_set(self, field):
        with pytest.raises(ValidationError):
            await adapter.update_by_id(None, uuid4(), {field: "tampered"})

    async def test_rejection_names_every_offending_field(self):
        with pytest.raises(ValidationError) as exc:
            await adapter.update_by_id(None, uuid4(), {"id": 1, "created_at": 2})

        assert "id" in exc.value.message
        assert "created_at" in exc.value.message

    async def test_validation_runs_before_any_database_work(self):
        with pytest.raises(ValidationError):
            await adapter.update_by_id(None, uuid4(), {"seat_limit": 5, "id": uuid4()})

from uuid import uuid4

import pytest

from src.core.exceptions import ValidationError
from src.documents.sqlalchemy import adapter
from src.documents.sqlalchemy.models import DocumentRow


def test_immutable_columns_are_not_updatable():
    assert adapter.UPDATABLE_FIELDS.isdisjoint({"id", "created_at", "updated_at"})


def test_the_whitelist_only_names_real_columns():
    columns = {column.name for column in DocumentRow.__table__.columns}

    assert adapter.UPDATABLE_FIELDS <= columns


def test_extraction_results_are_not_editable_by_hand():
    assert adapter.UPDATABLE_FIELDS.isdisjoint(
        {"extracted_text", "extracted_chars", "status", "organization_id"}
    )


async def test_an_unknown_field_is_rejected():
    with pytest.raises(ValidationError) as exc:
        await adapter.update_for_organization(None, uuid4(), uuid4(), {"nope": "x"})

    assert exc.value.code == "document_field_not_updatable"


@pytest.mark.parametrize("field", ["id", "status", "extracted_text", "organization_id"])
async def test_protected_columns_cannot_be_set(field):
    with pytest.raises(ValidationError):
        await adapter.update_for_organization(None, uuid4(), uuid4(), {field: "x"})


async def test_validation_runs_before_any_database_work():
    with pytest.raises(ValidationError):
        await adapter.update_for_organization(
            None, uuid4(), uuid4(), {"title": "fine", "status": "tampered"}
        )

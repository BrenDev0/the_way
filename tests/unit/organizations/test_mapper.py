from datetime import UTC, datetime
from uuid import uuid4

from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import mapper as organizations_mapper
from src.organizations.sqlalchemy.models import OrganizationRow


class TestOrganizationMapper:
    def test_row_to_domain(self):
        now = datetime.now(UTC)
        row = OrganizationRow(id=uuid4(), name="Acme Inc", seat_limit=25)
        row.created_at = now
        row.updated_at = now

        organization = organizations_mapper.row_to_domain(row)

        assert organization.id == row.id
        assert organization.name == "Acme Inc"
        assert organization.seat_limit == 25

    def test_domain_create_to_row(self):
        row = organizations_mapper.domain_create_to_row(OrganizationCreate(name="Acme Inc"))
        assert row.name == "Acme Inc"

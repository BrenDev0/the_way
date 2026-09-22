from src.organizations.domain import Organization, OrganizationCreate

from .models import OrganizationRow


def row_to_domain(row: OrganizationRow) -> Organization:
    return Organization(
        id=row.id,
        name=row.name,
        seat_limit=row.seat_limit,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def domain_create_to_row(organization: OrganizationCreate) -> OrganizationRow:
    return OrganizationRow(name=organization.name)

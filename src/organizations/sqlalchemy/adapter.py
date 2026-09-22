from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ValidationError
from src.organizations.domain import Organization, OrganizationCreate

from . import mapper
from .models import OrganizationRow

UPDATABLE_FIELDS = frozenset({"name", "seat_limit"})


async def create(session: AsyncSession, organization: OrganizationCreate) -> Organization:
    row = mapper.domain_create_to_row(organization)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def get_by_id(session: AsyncSession, organization_id: UUID) -> Organization | None:
    result = await session.execute(
        select(OrganizationRow).where(OrganizationRow.id == organization_id)
    )
    row = result.scalar_one_or_none()

    return mapper.row_to_domain(row) if row else None


async def update_by_id(
    session: AsyncSession,
    organization_id: UUID,
    changes: dict[str, Any],
) -> Organization | None:
    unknown = set(changes) - UPDATABLE_FIELDS
    if unknown:
        raise ValidationError(
            message=f"Cannot update: {', '.join(sorted(unknown))}",
            code="organization_field_not_updatable",
        )

    result = await session.execute(
        select(OrganizationRow).where(OrganizationRow.id == organization_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None

    for field, value in changes.items():
        setattr(row, field, value)

    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def delete_by_id(session: AsyncSession, organization_id: UUID) -> bool:
    result = await session.execute(
        delete(OrganizationRow)
        .where(OrganizationRow.id == organization_id)
        .returning(OrganizationRow.id)
    )
    return result.scalar_one_or_none() is not None

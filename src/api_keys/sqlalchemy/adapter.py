from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api_keys.domain import ApiKey, ApiKeyCreate, Provider
from src.users.sqlalchemy.models import UserRow

from . import mapper
from .models import ApiKeyRow


async def upsert(session: AsyncSession, api_key: ApiKeyCreate) -> ApiKey:
    result = await session.execute(
        select(ApiKeyRow).where(
            ApiKeyRow.organization_id == api_key.organization_id,
            ApiKeyRow.provider == api_key.provider,
        )
    )
    row = result.scalar_one_or_none()

    if row is None:
        row = mapper.domain_create_to_row(api_key)
        session.add(row)
    else:
        row.secret = api_key.encrypted_secret
        row.last_four = api_key.last_four
        row.account_id = api_key.encrypted_account_id
        row.model = api_key.model
        row.set_by = api_key.set_by

    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def list_for_organization(session: AsyncSession, organization_id: UUID) -> Sequence[ApiKey]:
    result = await session.execute(
        select(ApiKeyRow)
        .where(ApiKeyRow.organization_id == organization_id)
        .order_by(ApiKeyRow.provider)
    )
    return [mapper.row_to_domain(row) for row in result.scalars().all()]


async def list_for_user(session: AsyncSession, user_id: UUID) -> Sequence[ApiKey]:
    """The keys of the user's organization: a user holds none of their own."""
    result = await session.execute(
        select(ApiKeyRow)
        .join(UserRow, UserRow.organization_id == ApiKeyRow.organization_id)
        .where(UserRow.id == user_id)
        .order_by(ApiKeyRow.provider)
    )
    return [mapper.row_to_domain(row) for row in result.scalars().all()]


async def delete_for_organization(
    session: AsyncSession,
    organization_id: UUID,
    provider: Provider,
) -> bool:
    result = await session.execute(
        delete(ApiKeyRow)
        .where(ApiKeyRow.organization_id == organization_id, ApiKeyRow.provider == provider)
        .returning(ApiKeyRow.id)
    )
    return result.scalar_one_or_none() is not None

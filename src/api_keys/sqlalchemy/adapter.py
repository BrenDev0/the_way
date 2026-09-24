from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api_keys.domain import ApiKey, ApiKeyCreate

from . import mapper
from .models import ApiKeyRow


async def upsert(session: AsyncSession, api_key: ApiKeyCreate) -> ApiKey:
    result = await session.execute(
        select(ApiKeyRow).where(
            ApiKeyRow.user_id == api_key.user_id,
            ApiKeyRow.provider == api_key.provider,
        )
    )
    row = result.scalar_one_or_none()

    if row is None:
        row = mapper.domain_create_to_row(api_key)
        session.add(row)
    else:
        row.organization_id = api_key.organization_id
        row.secret = api_key.encrypted_secret
        row.last_four = api_key.last_four
        row.account_id = api_key.encrypted_account_id
        row.model = api_key.model
        row.issued_by = api_key.issued_by

    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def list_for_organization(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID | None = None,
) -> Sequence[ApiKey]:
    statement = select(ApiKeyRow).where(ApiKeyRow.organization_id == organization_id)
    if user_id is not None:
        statement = statement.where(ApiKeyRow.user_id == user_id)

    result = await session.execute(statement)
    return [mapper.row_to_domain(row) for row in result.scalars().all()]


async def list_for_user(session: AsyncSession, user_id: UUID) -> Sequence[ApiKey]:
    result = await session.execute(select(ApiKeyRow).where(ApiKeyRow.user_id == user_id))
    return [mapper.row_to_domain(row) for row in result.scalars().all()]


async def delete_for_organization(
    session: AsyncSession,
    api_key_id: UUID,
    organization_id: UUID,
) -> bool:
    result = await session.execute(
        delete(ApiKeyRow)
        .where(ApiKeyRow.id == api_key_id, ApiKeyRow.organization_id == organization_id)
        .returning(ApiKeyRow.id)
    )
    return result.scalar_one_or_none() is not None

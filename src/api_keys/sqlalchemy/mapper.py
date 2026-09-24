from src.api_keys.domain import ApiKey, ApiKeyCreate, Provider

from .models import ApiKeyRow


def row_to_domain(row: ApiKeyRow) -> ApiKey:
    return ApiKey(
        id=row.id,
        organization_id=row.organization_id,
        user_id=row.user_id,
        provider=Provider(row.provider),
        encrypted_secret=row.secret,
        last_four=row.last_four,
        encrypted_account_id=row.account_id,
        model=row.model,
        issued_by=row.issued_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def domain_create_to_row(api_key: ApiKeyCreate) -> ApiKeyRow:
    return ApiKeyRow(
        organization_id=api_key.organization_id,
        user_id=api_key.user_id,
        provider=api_key.provider,
        secret=api_key.encrypted_secret,
        last_four=api_key.last_four,
        account_id=api_key.encrypted_account_id,
        model=api_key.model,
        issued_by=api_key.issued_by,
    )

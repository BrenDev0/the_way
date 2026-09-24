from .domain import ApiKey
from .schemas import ApiKeyResponse


def domain_to_api_key_response(api_key: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=api_key.id,
        user_id=api_key.user_id,
        provider=api_key.provider,
        last_four=api_key.last_four,
        model=api_key.model,
        issued_by=api_key.issued_by,
        created_at=api_key.created_at,
        updated_at=api_key.updated_at,
    )

from collections.abc import Sequence
from uuid import UUID

from src.core.cryptography.ports import EncryptionService
from src.core.exceptions import ConflictError, NotFoundError, ValidationError
from src.core.llm.langchain import providers as llm_providers
from src.users.ports import GetUserByIdFn

from . import config
from .domain import LLM_PROVIDERS, ApiKey, ApiKeyCreate, Provider
from .ports import (
    DeleteApiKeyForOrganizationFn,
    ListApiKeysFn,
    ListApiKeysForUserFn,
    UpsertApiKeyFn,
)

LAST_FOUR_LENGTH = 4


def _not_found() -> NotFoundError:
    return NotFoundError(message="API key not found", code="api_key_not_found")


def _validate_model(provider: Provider, model: str | None) -> None:
    if model is None:
        return

    if provider not in LLM_PROVIDERS:
        raise ValidationError(
            message=f"{provider} credentials do not take a model",
            code="api_key_model_not_supported",
        )

    spec = llm_providers.spec_for(model)
    if spec.provider != provider:
        raise ValidationError(
            message=f"Model '{model}' does not belong to {provider}",
            code="api_key_model_provider_mismatch",
        )


async def issue_api_key(
    organization_id: UUID,
    user_id: UUID,
    provider: Provider,
    secret: str,
    issued_by: UUID,
    get_user_by_id_fn: GetUserByIdFn,
    upsert_api_key_fn: UpsertApiKeyFn,
    encryption_service: EncryptionService,
    account_id: str | None = None,
    model: str | None = None,
) -> ApiKey:
    if provider is Provider.GOHIGHLEVEL and not account_id:
        raise ValidationError(
            message="GoHighLevel credentials need a location id",
            code="api_key_account_id_required",
        )

    _validate_model(provider, model)

    target = await get_user_by_id_fn(user_id)
    if target is None or target.organization_id != organization_id:
        raise NotFoundError(message="User not found", code="user_not_found")

    return await upsert_api_key_fn(
        ApiKeyCreate(
            organization_id=organization_id,
            user_id=user_id,
            provider=provider,
            encrypted_secret=encryption_service.encrypt(secret),
            last_four=secret[-LAST_FOUR_LENGTH:],
            encrypted_account_id=(
                encryption_service.encrypt(account_id) if account_id else None
            ),
            model=model,
            issued_by=issued_by,
        )
    )


async def list_api_keys(
    organization_id: UUID,
    list_api_keys_fn: ListApiKeysFn,
    user_id: UUID | None = None,
) -> Sequence[ApiKey]:
    return await list_api_keys_fn(organization_id, user_id)


async def delete_api_key(
    api_key_id: UUID,
    organization_id: UUID,
    delete_api_key_for_organization_fn: DeleteApiKeyForOrganizationFn,
) -> None:
    if not await delete_api_key_for_organization_fn(api_key_id, organization_id):
        raise _not_found()


async def resolve_llm_credential(
    user_id: UUID,
    list_api_keys_for_user_fn: ListApiKeysForUserFn,
) -> ApiKey:
    held = {key.provider: key for key in await list_api_keys_for_user_fn(user_id)}

    for provider in config.PROVIDER_PRECEDENCE:
        credential = held.get(provider)
        if credential is not None:
            return credential

    raise ConflictError(
        message="No AI provider key has been issued to this user",
        code="api_key_not_configured",
    )


def model_for(credential: ApiKey) -> str:
    return credential.model or config.DEFAULT_MODEL[credential.provider]

from collections.abc import Iterable, Sequence
from uuid import UUID

from src.core.cryptography.ports import EncryptionService
from src.core.exceptions import ConflictError, NotFoundError, ValidationError
from src.core.llm.langchain import providers as llm_providers

from . import config
from .domain import LLM_PROVIDERS, ApiKey, ApiKeyCreate, Provider
from .ports import (
    DeleteApiKeyFn,
    ListApiKeysFn,
    ListApiKeysForUserFn,
    UpsertApiKeyFn,
)

LAST_FOUR_LENGTH = 4

NOT_SET_UP = (
    "Your organization's AI access has not been set up yet. "
    "Contact Xplorers to have it enabled."
)


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


async def set_api_key(
    organization_id: UUID,
    provider: Provider,
    secret: str,
    set_by: UUID,
    upsert_api_key_fn: UpsertApiKeyFn,
    encryption_service: EncryptionService,
    account_id: str | None = None,
    model: str | None = None,
) -> ApiKey:
    """Set (or replace) the organization's key for a provider. Only Xplorers staff reach
    this; the secret is stored encrypted and never leaves the server again."""
    secret = secret.strip()
    if not secret:
        raise ValidationError(message="The key cannot be empty", code="api_key_secret_required")

    if provider is Provider.GOHIGHLEVEL and not account_id:
        raise ValidationError(
            message="CX credentials need a location id",
            code="api_key_account_id_required",
        )

    _validate_model(provider, model)

    return await upsert_api_key_fn(
        ApiKeyCreate(
            organization_id=organization_id,
            provider=provider,
            encrypted_secret=encryption_service.encrypt(secret),
            last_four=secret[-LAST_FOUR_LENGTH:],
            encrypted_account_id=(
                encryption_service.encrypt(account_id.strip()) if account_id else None
            ),
            model=model,
            set_by=set_by,
        )
    )


async def list_api_keys(
    organization_id: UUID,
    list_api_keys_fn: ListApiKeysFn,
) -> Sequence[ApiKey]:
    return await list_api_keys_fn(organization_id)


async def delete_api_key(
    organization_id: UUID,
    provider: Provider,
    delete_api_key_fn: DeleteApiKeyFn,
) -> None:
    if not await delete_api_key_fn(organization_id, provider):
        raise _not_found()


def _holds_llm_credential(api_keys: Iterable[ApiKey]) -> bool:
    return any(key.provider in config.PROVIDER_PRECEDENCE for key in api_keys)


async def is_setup_complete(
    user_id: UUID,
    list_api_keys_for_user_fn: ListApiKeysForUserFn,
) -> bool:
    """Whether the user's organization has an AI provider key: it is the organization that
    is set up, not the person."""
    return _holds_llm_credential(await list_api_keys_for_user_fn(user_id))


async def organization_is_set_up(
    organization_id: UUID,
    list_api_keys_fn: ListApiKeysFn,
) -> bool:
    return _holds_llm_credential(await list_api_keys_fn(organization_id))


async def resolve_llm_credential(
    user_id: UUID,
    list_api_keys_for_user_fn: ListApiKeysForUserFn,
) -> ApiKey:
    held = {key.provider: key for key in await list_api_keys_for_user_fn(user_id)}

    for provider in config.PROVIDER_PRECEDENCE:
        credential = held.get(provider)
        if credential is not None:
            return credential

    raise ConflictError(message=NOT_SET_UP, code="api_key_not_configured")


def model_for(credential: ApiKey) -> str:
    return credential.model or config.DEFAULT_MODEL[credential.provider]

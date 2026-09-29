from collections.abc import Mapping, Sequence
from uuid import UUID

from src.core.cryptography.ports import EncryptionService
from src.core.exceptions import ConflictError
from src.core.llm.langchain import providers as llm_providers
from src.core.llm.langchain.adapter import LangchainLLM
from src.core.llm.ports import LLM
from src.core.tools.context import Credential, LLMFactory

from . import config
from .domain import Provider
from .ports import ListApiKeysForUserFn


async def load_credentials(
    user_id: UUID,
    list_api_keys_for_user_fn: ListApiKeysForUserFn,
    encryption_service: EncryptionService,
) -> dict[str, Credential]:
    """Every key issued to the user, decrypted and keyed by provider. Built once per run
    and handed to the tools that need it; it never leaves the worker."""
    return {
        str(key.provider): Credential(
            secret=encryption_service.decrypt(key.encrypted_secret),
            account_id=(
                encryption_service.decrypt(key.encrypted_account_id)
                if key.encrypted_account_id
                else None
            ),
            model=key.model,
        )
        for key in await list_api_keys_for_user_fn(user_id)
    }


def build_llm_factory(credentials: Mapping[str, Credential]) -> LLMFactory:
    async def llm_factory(preferred: Sequence[str] = (), temperature: float = 0.0) -> LLM:
        for model in preferred:
            spec = llm_providers.CATALOG.get(model)
            credential = credentials.get(spec.provider) if spec else None
            if credential is not None:
                return _build(model, temperature, credential.secret)

        for provider in config.PROVIDER_PRECEDENCE:
            credential = credentials.get(str(provider))
            if credential is not None:
                model = credential.model or config.DEFAULT_MODEL[Provider(provider)]
                return _build(model, temperature, credential.secret)

        raise ConflictError(
            message=(
                "Your account has not been set up yet. "
                "Ask an owner or admin in your organization to issue you an AI provider key."
            ),
            code="api_key_not_configured",
        )

    return llm_factory


def _build(model: str, temperature: float, api_key: str) -> LLM:
    return LangchainLLM(llm_providers.build_model(model, temperature, api_key=api_key))

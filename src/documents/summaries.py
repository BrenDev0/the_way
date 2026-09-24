from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.api_keys import use_cases as api_keys_use_cases
from src.api_keys.sqlalchemy import adapter as api_keys_adapter
from src.core.cryptography.ports import EncryptionService
from src.core.exceptions import ApplicationError
from src.core.llm import domain as llm_domain
from src.core.llm.langchain import providers as llm_providers
from src.core.llm.langchain.adapter import LangchainLLM

from . import config, prompt


def _clip(text: str) -> str:
    cleaned = " ".join(text.split()).strip().strip('"')
    if len(cleaned) <= config.MAX_GENERATED_DESCRIPTION_CHARS:
        return cleaned
    return cleaned[: config.MAX_GENERATED_DESCRIPTION_CHARS - 1].rstrip() + "…"


async def describe(
    session: AsyncSession,
    uploaded_by: UUID | None,
    title: str,
    text: str,
    encryption_service: EncryptionService,
) -> str | None:
    if uploaded_by is None or not text.strip():
        return None

    async def list_api_keys_for_user_fn(user_id: UUID):
        return await api_keys_adapter.list_for_user(session, user_id)

    try:
        credential = await api_keys_use_cases.resolve_llm_credential(
            user_id=uploaded_by,
            list_api_keys_for_user_fn=list_api_keys_for_user_fn,
        )
    except ApplicationError:
        return None

    model = config.SUMMARY_MODEL.get(credential.provider)
    if model is None:
        return None

    llm = LangchainLLM(
        llm_providers.build_model(
            model,
            config.SUMMARY_TEMPERATURE,
            api_key=encryption_service.decrypt(credential.encrypted_secret),
        )
    )

    completion = await llm.respond(
        [
            llm_domain.system(prompt.SUMMARY_SYSTEM),
            llm_domain.user(
                prompt.SUMMARY_USER.format(
                    title=title,
                    excerpt=text[: config.MAX_SUMMARY_INPUT_CHARS],
                )
            ),
        ]
    )

    return _clip(completion.text) or None

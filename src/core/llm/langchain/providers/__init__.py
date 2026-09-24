from langchain_core.language_models import BaseChatModel

from src.core.exceptions import ValidationError

from . import anthropic, openai
from .spec import ModelSpec

CATALOG: dict[str, ModelSpec] = {**openai.CATALOG, **anthropic.CATALOG}

BUILDERS = {
    openai.PROVIDER: openai.build,
    anthropic.PROVIDER: anthropic.build,
}


def available_models() -> list[str]:
    return sorted(CATALOG)


def spec_for(model: str) -> ModelSpec:
    spec = CATALOG.get(model)
    if spec is None:
        raise ValidationError(
            message=f"Unknown model '{model}'",
            code="llm_model_not_available",
        )
    return spec


def build_model(model: str, temperature: float = 0.0, *, api_key: str) -> BaseChatModel:
    spec = spec_for(model)
    return BUILDERS[spec.provider](spec, temperature, api_key)

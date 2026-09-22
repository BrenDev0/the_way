from typing import Any

from langchain_core.language_models import BaseChatModel

from src.core.settings import settings

from .spec import ModelSpec

PROVIDER = "anthropic"

MODELS = (
    ModelSpec("claude-opus-5", PROVIDER, accepts_temperature=True),
    ModelSpec("claude-sonnet-5", PROVIDER, accepts_temperature=True),
    ModelSpec("claude-fable-5-1", PROVIDER, accepts_temperature=True),
    ModelSpec("claude-haiku-4-5-20251001", PROVIDER, accepts_temperature=True),
)

CATALOG = {spec.name: spec for spec in MODELS}


def build(spec: ModelSpec, temperature: float) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    kwargs: dict[str, Any] = {
        "model_name": spec.name,
        "api_key": settings.require_api_key(PROVIDER),
    }
    if spec.accepts_temperature:
        kwargs["temperature"] = temperature

    return ChatAnthropic(**kwargs)

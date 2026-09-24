from typing import Any

from langchain_core.language_models import BaseChatModel

from .spec import ModelSpec

PROVIDER = "openai"

MODELS = (
    ModelSpec("gpt-5.4", PROVIDER),
    ModelSpec("gpt-5.4-mini", PROVIDER),
    ModelSpec("gpt-5.4-nano", PROVIDER),
    ModelSpec("gpt-5.2", PROVIDER),
    ModelSpec("gpt-5.1", PROVIDER),
    ModelSpec("gpt-5", PROVIDER),
    ModelSpec("gpt-5-mini", PROVIDER),
    ModelSpec("gpt-5-nano", PROVIDER),
    ModelSpec("gpt-4.1", PROVIDER, accepts_temperature=True),
    ModelSpec("gpt-4.1-mini", PROVIDER, accepts_temperature=True),
    ModelSpec("gpt-4.1-nano", PROVIDER, accepts_temperature=True),
    ModelSpec("gpt-4o", PROVIDER, accepts_temperature=True),
    ModelSpec("gpt-4o-mini", PROVIDER, accepts_temperature=True),
    ModelSpec("o4-mini", PROVIDER),
    ModelSpec("o3", PROVIDER),
    ModelSpec("o3-mini", PROVIDER),
)

CATALOG = {spec.name: spec for spec in MODELS}


def build(spec: ModelSpec, temperature: float, api_key: str) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {"model": spec.name, "api_key": api_key}
    if spec.accepts_temperature:
        kwargs["temperature"] = temperature

    return ChatOpenAI(**kwargs)

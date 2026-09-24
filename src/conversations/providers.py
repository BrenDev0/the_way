from src.core.llm.langchain import providers as llm_providers
from src.core.llm.langchain.adapter import LangchainLLM
from src.core.llm.ports import LLM

from . import config


def provide_llm(
    model: str,
    api_key: str,
    temperature: float = config.TEMPERATURE,
    stream: bool = False,
) -> LLM:
    return LangchainLLM(
        llm_providers.build_model(model, temperature, api_key=api_key),
        stream=stream,
    )

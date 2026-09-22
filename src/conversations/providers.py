from src.core.llm.langchain import providers as llm_providers
from src.core.llm.langchain.adapter import LangchainLLM
from src.core.llm.ports import LLM

from . import config


def provide_llm(stream: bool = False) -> LLM:
    return LangchainLLM(
        llm_providers.build_model(config.MODEL, config.TEMPERATURE),
        stream=stream,
    )

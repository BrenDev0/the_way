import pytest
from helpers import FakeLLM, make_completion

from src.conversations import config, prompt, use_cases
from src.core.llm import domain


def test_the_system_prompt_comes_first():
    messages = use_cases.build_messages("hello")

    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == prompt.SYSTEM


def test_the_user_message_comes_last():
    messages = use_cases.build_messages("hello")

    assert messages[-1] == {"role": "user", "content": "hello"}


def test_history_sits_between_the_prompt_and_the_new_message():
    history = [domain.user("earlier"), domain.assistant("reply")]

    messages = use_cases.build_messages("now", history)

    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]


def test_history_is_not_mutated():
    history = [domain.user("earlier")]

    use_cases.build_messages("now", history)

    assert len(history) == 1


def test_the_prompt_is_not_stored_in_history():
    history = [domain.user("earlier"), domain.assistant("reply")]

    messages = use_cases.build_messages("now", history)

    assert sum(1 for m in messages if m["role"] == "system") == 1


async def test_reply_returns_the_completion():
    llm = FakeLLM("the answer")

    completion = await use_cases.reply("hello", llm)

    assert completion.text == "the answer"


async def test_reply_sends_the_built_conversation():
    llm = FakeLLM("the answer")

    await use_cases.reply("hello", llm)

    sent = llm.received[0]
    assert sent[0]["role"] == "system"
    assert sent[-1]["content"] == "hello"


async def test_reply_carries_history_through():
    llm = FakeLLM("the answer")
    history = [domain.user("earlier"), domain.assistant("reply")]

    await use_cases.reply("now", llm, history)

    assert [m["role"] for m in llm.received[0]] == ["system", "user", "assistant", "user"]


async def test_the_returned_message_can_be_appended_to_history():
    llm = FakeLLM("the answer")

    completion = await use_cases.reply("hello", llm)

    assert completion.message["role"] == "assistant"
    assert completion.message["content"] == "the answer"


async def test_an_empty_answer_is_passed_through_not_swallowed():
    llm = FakeLLM(make_completion(""))

    completion = await use_cases.reply("hello", llm)

    assert completion.text == ""


async def test_usage_is_reported():
    from src.core.llm.domain import TokenUsage

    llm = FakeLLM(make_completion("hi", usage=TokenUsage(10, 4, 14)))

    completion = await use_cases.reply("hello", llm)

    assert completion.usage.total_tokens == 14


def test_the_configured_model_exists_in_the_catalog():
    from src.core.llm.langchain import providers

    assert config.MODEL in providers.CATALOG


def test_a_temperature_is_configured():
    assert 0.0 <= config.TEMPERATURE <= 2.0


def test_provide_llm_builds_a_working_adapter(monkeypatch):
    from src.conversations import providers as orchestrator_providers
    from src.core.settings import settings

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")

    llm = orchestrator_providers.provide_llm()

    assert hasattr(llm, "respond")


@pytest.mark.parametrize("phrase", ["do not know", "Never invent"])
def test_the_prompt_forbids_invention(phrase):
    assert phrase in prompt.SYSTEM

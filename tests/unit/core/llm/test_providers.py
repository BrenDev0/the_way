import json
from itertools import pairwise

import pytest
from langchain_core.messages import convert_to_messages

from src.core.exceptions import ValidationError
from src.core.llm import domain
from src.core.llm.domain import ToolCall
from src.core.llm.langchain import providers
from src.core.llm.langchain.adapter import _canonical
from src.core.llm.langchain.providers import anthropic, openai

OPENAI_KEY = "sk-openai-test"
ANTHROPIC_KEY = "sk-ant-test"


def test_catalog_merges_every_provider():
    assert set(providers.CATALOG) == set(openai.CATALOG) | set(anthropic.CATALOG)


def test_no_model_name_is_claimed_by_two_providers():
    assert not set(openai.CATALOG) & set(anthropic.CATALOG)


def test_every_spec_has_a_builder():
    for spec in providers.CATALOG.values():
        assert spec.provider in providers.BUILDERS


def test_every_catalog_key_matches_its_spec_name():
    for name, spec in providers.CATALOG.items():
        assert name == spec.name


def test_available_models_is_sorted():
    assert providers.available_models() == sorted(providers.CATALOG)


def test_an_unknown_model_is_rejected():
    with pytest.raises(ValidationError) as exc:
        providers.spec_for("gpt-nonexistent")

    assert exc.value.code == "llm_model_not_available"
    assert exc.value.status_code == 422


def test_the_rejection_names_the_model():
    with pytest.raises(ValidationError) as exc:
        providers.spec_for("gpt-nonexistent")

    assert "gpt-nonexistent" in exc.value.message


def test_builds_an_openai_client():
    model = providers.build_model("gpt-4o", api_key=OPENAI_KEY)

    assert type(model).__name__ == "ChatOpenAI"
    assert model.model_name == "gpt-4o"


def test_builds_an_anthropic_client():
    from langchain_anthropic import ChatAnthropic

    model = providers.build_model("claude-sonnet-5", api_key=ANTHROPIC_KEY)

    assert isinstance(model, ChatAnthropic)
    assert model.model == "claude-sonnet-5"


def _claude_payload(messages):
    model = providers.build_model("claude-sonnet-5", api_key=ANTHROPIC_KEY)
    return model._get_request_payload(convert_to_messages(messages))


def test_claude_caches_the_tools_and_system_prompt_for_an_hour():
    payload = _claude_payload([domain.system("prompt"), domain.system("index"), domain.user("hi")])

    assert payload["system"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "cache_control" not in payload["system"][0]  # one breakpoint is enough


def test_claude_caches_the_conversation_up_to_its_end():
    payload = _claude_payload([domain.system("prompt"), domain.user("hi")])

    assert payload["cache_control"] == {"type": "ephemeral"}


def test_a_system_note_inside_the_conversation_reaches_claude_as_the_users():
    payload = _claude_payload([
        domain.system("prompt"),
        domain.user("hi"),
        domain.assistant("hello"),
        domain.system("A background task finished."),
        domain.system("Current date: Monday."),
    ])

    assert payload["system"][0]["text"] == "prompt"
    last = payload["messages"][-1]
    assert last["role"] == "user"
    texts = [block["text"] for block in last["content"]]
    assert "A background task finished." in texts[0] and "<system-reminder>" in texts[0]
    assert "Current date: Monday." in texts[1]


def _sent(messages):
    """The request as Claude would get it, minus the moving breakpoint -- which differs
    between requests by design and is no part of what must stay the same."""
    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k != "cache_control"}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value

    model = providers.build_model("claude-sonnet-5", api_key=ANTHROPIC_KEY)
    payload = model._get_request_payload(convert_to_messages(_canonical(messages)))
    return strip(payload["system"]), json.dumps(strip(payload["messages"]))


def _shuffled(value):
    if isinstance(value, dict):
        return {key: _shuffled(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [_shuffled(item) for item in value]
    return value


def test_each_tool_loop_iteration_resends_the_last_one_unchanged_so_it_is_read_from_cache():
    messages = [domain.system("prompt"), domain.user("summarise these files"), domain.system("ctx")]
    requests = []
    for step in range(5):
        requests.append(_sent(messages))
        call = ToolCall(id=f"c{step}", name="ReadFile", args={"path": f"f{step}.txt", "limit": 9000})
        messages += [domain.assistant("", (call,)), domain.tool_result(call.id, "x" * 5000)]

    for before, after in pairwise(requests):
        assert after[0] == before[0]
        # what was sent last time is exactly the start of what is sent now, minus the
        # closing bracket of the message list -- so it is all a cache read
        assert after[1].startswith(before[1][:-1])


def test_history_reloaded_from_the_database_sends_the_same_bytes():
    call = ToolCall(id="c1", name="WriteFile", args={"path": "a.md", "content": "hi", "mode": "w"})
    messages = [
        domain.system("prompt"),
        domain.user("write it"),
        domain.assistant([{"type": "text", "text": "ok"}, {"type": "tool_use", "id": "c1", "name": "WriteFile", "input": call.args}], (call,)),
        domain.tool_result("c1", "written"),
    ]

    # JSONB hands keys back in its own order, not the order they were written in
    assert _sent(_shuffled(messages)) == _sent(messages)


def test_a_note_after_tool_results_follows_them_in_the_same_turn():
    payload = _claude_payload([
        domain.system("prompt"),
        domain.user("read it"),
        domain.assistant("", (ToolCall(id="c1", name="ReadFile", args={}),)),
        domain.tool_result("c1", "contents"),
        domain.system("Wrap up now."),
    ])

    last = payload["messages"][-1]
    assert [block["type"] for block in last["content"]] == ["tool_result", "text"]


def test_the_supplied_key_reaches_the_openai_client():
    model = providers.build_model("gpt-4o", api_key=OPENAI_KEY)

    assert model.openai_api_key.get_secret_value() == OPENAI_KEY


def test_the_supplied_key_reaches_the_anthropic_client():
    model = providers.build_model("claude-sonnet-5", api_key=ANTHROPIC_KEY)

    assert model.anthropic_api_key.get_secret_value() == ANTHROPIC_KEY


def test_two_callers_get_clients_with_their_own_keys():
    first = providers.build_model("gpt-4o", api_key="sk-first")
    second = providers.build_model("gpt-4o", api_key="sk-second")

    assert first.openai_api_key.get_secret_value() == "sk-first"
    assert second.openai_api_key.get_secret_value() == "sk-second"


def test_a_key_must_be_supplied():
    with pytest.raises(TypeError):
        providers.build_model("gpt-4o")  # type: ignore[call-arg]


def test_temperature_is_applied_when_the_model_accepts_it():
    model = providers.build_model("gpt-4o", temperature=0.9, api_key=OPENAI_KEY)

    assert model.temperature == 0.9


def test_temperature_is_omitted_when_the_model_rejects_it():
    model = providers.build_model("gpt-5.4", temperature=0.9, api_key=OPENAI_KEY)

    assert model.temperature != 0.9

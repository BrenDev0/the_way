import json

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from pydantic import BaseModel

from src.core.exceptions import InternalServerError
from src.core.llm import domain
from src.core.llm.domain import TokenUsage, ToolCall
from src.core.llm.langchain.adapter import LangchainLLM


class FakeChatModel:
    def __init__(self, result=None, chunks=None):
        self.bound = None
        self._result = result
        self._chunks = chunks or []
        self.received = None

    def bind_tools(self, tools):
        self.bound = tuple(tools)
        return self

    async def ainvoke(self, messages):
        self.received = messages
        return self._result

    async def astream(self, messages):
        self.received = messages
        for chunk in self._chunks:
            yield chunk


def conversation():
    return [
        domain.system("you are a bot"),
        domain.user("read a file"),
    ]


async def test_plain_text_completion():
    model = FakeChatModel(AIMessage(content="  hello  "))

    completion = await LangchainLLM(model).respond(conversation())

    assert completion.text == "hello"
    assert completion.tool_calls == ()


async def test_block_content_is_flattened_to_text():
    model = FakeChatModel(
        AIMessage(content=[{"type": "text", "text": "hi"}, {"type": "thinking", "thinking": "..."}])
    )

    completion = await LangchainLLM(model).respond(conversation())

    assert completion.text == "hi"


async def test_block_content_is_preserved_on_the_stored_message():
    blocks = [{"type": "text", "text": "hi"}, {"type": "thinking", "thinking": "..."}]
    model = FakeChatModel(AIMessage(content=blocks))

    completion = await LangchainLLM(model).respond(conversation())

    assert completion.message["content"] == blocks


async def test_tool_calls_are_returned():
    model = FakeChatModel(
        AIMessage(
            content="",
            tool_calls=[
                {"id": "c1", "name": "ReadFile", "args": {"path": "x.txt"}, "type": "tool_call"}
            ],
        )
    )

    completion = await LangchainLLM(model).respond(conversation())

    assert len(completion.tool_calls) == 1
    assert completion.tool_calls[0].id == "c1"
    assert completion.tool_calls[0].name == "ReadFile"
    assert completion.tool_calls[0].args == {"path": "x.txt"}


async def test_assistant_message_carries_the_tool_calls():
    model = FakeChatModel(
        AIMessage(
            content="",
            tool_calls=[
                {"id": "c1", "name": "ReadFile", "args": {"path": "x.txt"}, "type": "tool_call"}
            ],
        )
    )

    completion = await LangchainLLM(model).respond(conversation())

    assert completion.message["role"] == "assistant"
    assert completion.message["tool_calls"][0]["id"] == "c1"


async def test_the_returned_message_is_json_serialisable():
    model = FakeChatModel(
        AIMessage(
            content=[{"type": "text", "text": "hi"}],
            tool_calls=[
                {"id": "c1", "name": "ReadFile", "args": {"path": "x.txt"}, "type": "tool_call"}
            ],
        )
    )

    completion = await LangchainLLM(model).respond(conversation())

    assert json.loads(json.dumps(completion.message)) == completion.message


async def test_a_resumed_conversation_is_accepted_verbatim():
    model = FakeChatModel(AIMessage(content="done"))
    llm = LangchainLLM(model)

    suspended = [
        *conversation(),
        domain.assistant("", (ToolCall(id="c1", name="ReadFile", args={}),)),
        domain.tool_result("c1", "file contents"),
    ]
    reloaded = json.loads(json.dumps(suspended))

    completion = await llm.respond(reloaded)

    assert completion.text == "done"
    assert [type(m).__name__ for m in model.received] == [
        "SystemMessage",
        "HumanMessage",
        "AIMessage",
        "ToolMessage",
    ]


async def test_usage_is_extracted():
    model = FakeChatModel(
        AIMessage(
            content="hi",
            usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
        )
    )

    completion = await LangchainLLM(model).respond(conversation())

    assert completion.usage == TokenUsage(input_tokens=10, output_tokens=4, total_tokens=14)


async def test_missing_usage_is_zeroed():
    completion = await LangchainLLM(FakeChatModel(AIMessage(content="hi"))).respond(conversation())

    assert completion.usage == TokenUsage()


def test_usage_accumulates_across_turns():
    a = TokenUsage(input_tokens=10, output_tokens=4, total_tokens=14)
    b = TokenUsage(input_tokens=5, output_tokens=2, total_tokens=7)

    assert a + b == TokenUsage(input_tokens=15, output_tokens=6, total_tokens=21)


async def test_streaming_merges_chunks():
    model = FakeChatModel(
        chunks=[AIMessageChunk(content="hel"), AIMessageChunk(content="lo")],
    )

    completion = await LangchainLLM(model, stream=True).respond(conversation())

    assert completion.text == "hello"


async def test_streaming_merges_tool_call_fragments():
    model = FakeChatModel(
        chunks=[
            AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "ReadFile",
                        "args": '{"pa',
                        "id": "c1",
                        "index": 0,
                        "type": "tool_call_chunk",
                    }
                ],
            ),
            AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": None,
                        "args": 'th":"x"}',
                        "id": None,
                        "index": 0,
                        "type": "tool_call_chunk",
                    }
                ],
            ),
        ],
    )

    completion = await LangchainLLM(model, stream=True).respond(conversation())

    assert completion.tool_calls[0].args == {"path": "x"}


async def test_a_tool_call_without_an_id_is_an_error():
    model = FakeChatModel(
        AIMessage(
            content="",
            tool_calls=[
                {"id": None, "name": "ReadFile", "args": {}, "type": "tool_call"}
            ],
        )
    )

    with pytest.raises(InternalServerError) as exc:
        await LangchainLLM(model).respond(conversation())

    assert exc.value.code == "llm_tool_call_without_id"


async def test_an_empty_stream_is_an_error():
    with pytest.raises(InternalServerError) as exc:
        await LangchainLLM(FakeChatModel(chunks=[]), stream=True).respond(conversation())

    assert exc.value.code == "llm_empty_response"


async def test_openai_shape_plain_answer():
    model = FakeChatModel(AIMessage(content="hello"))

    completion = await LangchainLLM(model).respond(conversation())

    assert completion.text == "hello"
    assert completion.message["content"] == "hello"


async def test_openai_shape_with_tool_calls():
    model = FakeChatModel(
        AIMessage(
            content="",
            tool_calls=[{"id": "c1", "name": "ReadFile", "args": {}, "type": "tool_call"}],
        )
    )

    completion = await LangchainLLM(model).respond(conversation())

    assert completion.text == ""
    assert completion.tool_calls[0].name == "ReadFile"


async def test_anthropic_shape_single_text_block_arrives_as_a_string():
    model = FakeChatModel(AIMessage(content="hello"))

    completion = await LangchainLLM(model).respond(conversation())

    assert completion.text == "hello"


async def test_anthropic_shape_tool_use_arrives_as_a_block_list():
    content = [
        {"type": "text", "text": "Let me look."},
        {"type": "tool_use", "id": "c1", "name": "ReadFile", "input": {"path": "x.txt"}},
    ]
    model = FakeChatModel(
        AIMessage(
            content=content,
            tool_calls=[
                {"id": "c1", "name": "ReadFile", "args": {"path": "x.txt"}, "type": "tool_call"}
            ],
        )
    )

    completion = await LangchainLLM(model).respond(conversation())

    assert completion.text == "Let me look."
    assert completion.tool_calls[0].id == "c1"
    assert completion.message["content"] == content


async def test_anthropic_shape_thinking_blocks_are_kept_but_not_spoken():
    content = [
        {"type": "thinking", "thinking": "internal reasoning", "signature": "sig"},
        {"type": "text", "text": "the answer"},
    ]
    model = FakeChatModel(AIMessage(content=content))

    completion = await LangchainLLM(model).respond(conversation())

    assert completion.text == "the answer"
    assert "internal reasoning" not in completion.text
    assert completion.message["content"] == content


async def test_anthropic_shape_tool_use_with_no_commentary():
    content = [{"type": "tool_use", "id": "c1", "name": "ReadFile", "input": {}}]
    model = FakeChatModel(
        AIMessage(
            content=content,
            tool_calls=[{"id": "c1", "name": "ReadFile", "args": {}, "type": "tool_call"}],
        )
    )

    completion = await LangchainLLM(model).respond(conversation())

    assert completion.text == ""
    assert completion.tool_calls[0].name == "ReadFile"


async def test_every_provider_shape_survives_persistence():
    shapes = [
        "plain string",
        [{"type": "text", "text": "hi"}],
        [
            {"type": "thinking", "thinking": "r", "signature": "s"},
            {"type": "text", "text": "hi"},
        ],
        [{"type": "tool_use", "id": "c1", "name": "ReadFile", "input": {"path": "x"}}],
    ]

    for content in shapes:
        completion = await LangchainLLM(FakeChatModel(AIMessage(content=content))).respond(
            conversation()
        )
        assert json.loads(json.dumps(completion.message)) == completion.message


class Weather(BaseModel):
    city: str


class Forecast(BaseModel):
    city: str
    days: int


async def test_no_tools_are_bound_when_none_are_given():
    model = FakeChatModel(AIMessage(content="hi"))

    await LangchainLLM(model).respond(conversation())

    assert model.bound is None


async def test_the_given_tools_are_bound():
    model = FakeChatModel(AIMessage(content="hi"))

    await LangchainLLM(model).respond(conversation(), (Weather, Forecast))

    assert model.bound == (Weather, Forecast)


async def test_tools_are_bound_when_streaming():
    model = FakeChatModel(chunks=[AIMessageChunk(content="hi")])

    await LangchainLLM(model, stream=True).respond(conversation(), (Weather,))

    assert model.bound == (Weather,)


async def test_an_empty_tool_sequence_leaves_the_model_alone():
    model = FakeChatModel(AIMessage(content="hi"))

    await LangchainLLM(model).respond(conversation(), ())

    assert model.bound is None

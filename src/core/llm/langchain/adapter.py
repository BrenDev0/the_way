from collections.abc import Sequence
from typing import Any, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, convert_to_messages
from langchain_core.messages.tool import ToolCall as LangchainToolCall
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from src.core.exceptions import InternalServerError

from ..domain import Completion, Message, TokenUsage, ToolCall, assistant
from ..ports import TextListener


class LangchainLLM:
    def __init__(self, model: BaseChatModel, stream: bool = False) -> None:
        self._model = model
        self._stream = stream

    async def respond(
        self,
        messages: list[Message],
        tools: Sequence[type[BaseModel]] = (),
        on_text: TextListener | None = None,
    ) -> Completion:
        result = await self._generate(messages, tools, on_text)
        tool_calls = tuple(_tool_call(call) for call in result.tool_calls)
        return Completion(
            message=assistant(result.content, tool_calls),
            text=str(result.text).strip(),
            tool_calls=tool_calls,
            usage=_usage(result),
        )

    async def _generate(
        self,
        messages: list[Message],
        tools: Sequence[type[BaseModel]],
        on_text: TextListener | None = None,
    ) -> AIMessage:
        converted = convert_to_messages(messages)
        model: Runnable = self._model.bind_tools(list(tools)) if tools else self._model

        # Streamed whenever someone is listening, so the reply appears as it is written.
        if not self._stream and on_text is None:
            return cast("AIMessage", await model.ainvoke(converted))

        result: Any = None
        async for chunk in model.astream(converted):
            result = chunk if result is None else result + chunk
            if on_text is not None:
                text = _chunk_text(chunk.content)
                if text:
                    await on_text(text)

        if result is None:
            raise InternalServerError(
                message="Unable to process request at this time",
                code="llm_empty_response",
            )
        return cast("AIMessage", result)


def _chunk_text(content: Any) -> str:
    """OpenAI streams plain strings; Anthropic streams a list of typed blocks, of which only
    the text ones are reply (the rest are tool-call argument fragments)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") in (None, "text", "text_delta")
        )
    return ""


def _tool_call(call: LangchainToolCall) -> ToolCall:
    call_id = call.get("id")
    if not call_id:
        raise InternalServerError(
            message="Unable to process request at this time",
            code="llm_tool_call_without_id",
        )
    return ToolCall(id=call_id, name=call["name"], args=call["args"])


def _usage(result: AIMessage) -> TokenUsage:
    usage = getattr(result, "usage_metadata", None) or {}
    return TokenUsage(
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
    )

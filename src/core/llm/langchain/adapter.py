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
from .errors import unavailable


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
        try:
            result = await self._generate(messages, tools, on_text)
        except Exception as exc:
            if (passing := unavailable(exc)) is not None:
                raise passing from exc
            raise
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
        converted = convert_to_messages(_canonical(messages))
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


def _canonical(value: Any) -> Any:
    """Every dict's keys in one order. The provider caches the prompt up to its first
    differing byte, and the stored history comes back from the database (JSONB) with its
    keys reordered -- tool arguments sent as {path, content} in a turn would be resent as
    {content, path} the next, and everything after the first tool call billed again."""
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


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
    # Both providers report the cached share here; OpenAI never reports a write.
    details = usage.get("input_token_details") or {}
    return TokenUsage(
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
        cache_read_tokens=details.get("cache_read") or 0,
        cache_write_tokens=details.get("cache_creation") or 0,
    )

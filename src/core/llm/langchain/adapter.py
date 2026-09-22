from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, convert_to_messages
from langchain_core.messages.tool import ToolCall as LangchainToolCall

from src.core.exceptions import InternalServerError

from ..domain import Completion, Message, TokenUsage, ToolCall, assistant


class LangchainLLM:
    def __init__(self, model: BaseChatModel, stream: bool = False) -> None:
        self._model = model
        self._stream = stream

    async def respond(self, messages: list[Message]) -> Completion:
        result = await self._generate(messages)
        tool_calls = tuple(_tool_call(call) for call in result.tool_calls)
        return Completion(
            message=assistant(result.content, tool_calls),
            text=str(result.text).strip(),
            tool_calls=tool_calls,
            usage=_usage(result),
        )

    async def _generate(self, messages: list[Message]) -> AIMessage:
        converted = convert_to_messages(messages)

        if not self._stream:
            return await self._model.ainvoke(converted)

        result = None
        async for chunk in self._model.astream(converted):
            result = chunk if result is None else result + chunk

        if result is None:
            raise InternalServerError(
                message="Unable to process request at this time",
                code="llm_empty_response",
            )
        return result


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

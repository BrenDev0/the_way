from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage

from .spec import ModelSpec

PROVIDER = "anthropic"

MODELS = (
    ModelSpec("claude-opus-5", PROVIDER, accepts_temperature=True),
    ModelSpec("claude-sonnet-5", PROVIDER, accepts_temperature=True),
    ModelSpec("claude-fable-5-1", PROVIDER, accepts_temperature=True),
    ModelSpec("claude-haiku-4-5-20251001", PROVIDER, accepts_temperature=True),
)

CATALOG = {spec.name: spec for spec in MODELS}

# The tools and system prompt are the same for every conversation and run, and a user
# often answers after more than five minutes: an hour keeps them cached across that gap.
# The conversation behind them grows every request, and those come seconds apart within
# a turn -- the default five minutes, refreshed by each read, is the cheaper write there.
# The longer-lived breakpoint must come first, and does: system renders before messages.
PREFIX_CACHE = {"type": "ephemeral", "ttl": "1h"}
HISTORY_CACHE = {"type": "ephemeral"}

# A system note met after the conversation has begun (a finished task's report, the
# per-turn context, the wrap-up nudge) goes on the user's side: Claude refuses a system
# message there.
NOTE = "<system-reminder>\n{text}\n</system-reminder>"


def build(spec: ModelSpec, temperature: float, api_key: str) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    class CachedChatAnthropic(ChatAnthropic):
        """Claude with prompt caching: a breakpoint after the system prompt and one that
        moves with the end of the conversation, so each request bills in full only what
        was added since the last."""

        def _get_request_payload(self, input_: Any, *, stop: Any = None, **kwargs: Any) -> dict:
            messages = notes_as_user(self._convert_input(input_).to_messages())
            payload = super()._get_request_payload(messages, stop=stop, **kwargs)
            mark_system(payload)
            payload.setdefault("cache_control", HISTORY_CACHE)
            return payload

    kwargs: dict[str, Any] = {
        "model_name": spec.name,
        "api_key": api_key,
    }
    if spec.accepts_temperature:
        kwargs["temperature"] = temperature

    return CachedChatAnthropic(**kwargs)


def notes_as_user(messages: list[BaseMessage]) -> list[BaseMessage]:
    """The leading system messages are the system prompt; a later one is re-sent as a
    note in the user's turn."""
    out: list[BaseMessage] = []
    opening = True
    for message in messages:
        if message.type != "system":
            opening = False
        elif not opening:
            message = HumanMessage(NOTE.format(text=message.text))
        out.append(message)
    return out


def mark_system(payload: dict[str, Any]) -> None:
    """The long-lived breakpoint, on the last system block -- it caches the tools too."""
    system = payload.get("system")
    if not system:
        return
    blocks = [{"type": "text", "text": system}] if isinstance(system, str) else list(system)
    last = blocks[-1]
    if isinstance(last, dict) and last.get("type") == "text":
        blocks[-1] = {**last, "cache_control": PREFIX_CACHE}
        payload["system"] = blocks

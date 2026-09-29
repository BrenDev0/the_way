from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from pydantic import BaseModel

from .domain import Completion, Message

# Called with each piece of reply text as the model writes it.
TextListener = Callable[[str], Awaitable[None]]


class LLM(Protocol):
    async def respond(
        self,
        messages: list[Message],
        tools: Sequence[type[BaseModel]] = (),
        on_text: TextListener | None = None,
    ) -> Completion: ...

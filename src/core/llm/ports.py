from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel

from .domain import Completion, Message


class LLM(Protocol):
    async def respond(
        self,
        messages: list[Message],
        tools: Sequence[type[BaseModel]] = (),
    ) -> Completion: ...

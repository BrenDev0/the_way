from typing import Protocol

from .domain import Completion, Message


class LLM(Protocol):
    async def respond(self, messages: list[Message]) -> Completion: ...

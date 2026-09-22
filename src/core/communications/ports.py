from typing import Protocol

from .domain import Email


class EmailSender(Protocol):
    async def send(self, email: Email) -> None: ...

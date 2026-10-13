from dataclasses import dataclass
from typing import Protocol

from src.render.schemas import CheckResponse


class RenderUnavailable(RuntimeError):
    """The render service is not configured, not reachable, or not answering. Callers
    fall back to WeasyPrint or to reading the page; nothing is blocked on it."""


@dataclass(frozen=True)
class Rendered:
    content: bytes
    # the page's laid-out height in CSS pixels
    height: int
    # the bottom was cut to stay within the size limit
    truncated: bool = False
    # below 1 when a tall page was shrunk onto one PDF page
    scale: float = 1.0
    # how many addresses the page asked for and was refused
    blocked: int = 0


class Renderer(Protocol):
    async def png(
        self, html: str, width: int, full_page: bool = True, scale: int = 1
    ) -> Rendered: ...

    async def scroll_pdf(self, html: str, width: int) -> Rendered: ...

    async def paged_pdf(self, html: str, page_size: str = "Letter") -> Rendered: ...

    async def check(self, html: str) -> CheckResponse: ...

    async def healthy(self) -> bool: ...

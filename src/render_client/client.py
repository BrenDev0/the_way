"""How the API and worker reach the render service. Imports nothing from Playwright, which
is only installed in the render image."""

import httpx

from src.render.config import SECRET_HEADER
from src.render.schemas import (
    BLOCKED_HEADER,
    HEIGHT_HEADER,
    SCALE_HEADER,
    TRUNCATED_HEADER,
    CheckRequest,
    CheckResponse,
    PdfRequest,
    PngRequest,
)

from .ports import Rendered, Renderer, RenderUnavailable

# Longer than the service's own limit, so its 504 arrives before this gives up.
TIMEOUT = httpx.Timeout(45.0, connect=3.0)


class HttpRenderer:
    def __init__(self, base_url: str, secret: str, transport: httpx.AsyncBaseTransport | None = None):
        self._base_url = base_url.rstrip("/")
        self._secret = secret
        self._transport = transport

    async def _post(self, path: str, body: dict) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=TIMEOUT, transport=self._transport
            ) as client:
                response = await client.post(path, json=body, headers={SECRET_HEADER: self._secret})
        except httpx.HTTPError as exc:
            raise RenderUnavailable(f"render service not reachable: {type(exc).__name__}") from exc
        if response.status_code in (401, 502, 503):
            raise RenderUnavailable(f"render service refused: {response.status_code} {response.text[:200]}")
        if response.status_code >= 400:
            # The page's problem (too slow, navigated away, would not render): the caller
            # passes this on, it is not the service being down.
            detail = response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else response.text
            raise ValueError(str(detail)[:500])
        return response

    @staticmethod
    def _rendered(response: httpx.Response) -> Rendered:
        headers = response.headers
        return Rendered(
            content=response.content,
            height=int(headers.get(HEIGHT_HEADER, "0")),
            truncated=headers.get(TRUNCATED_HEADER) == "1",
            scale=float(headers.get(SCALE_HEADER, "1")),
            blocked=int(headers.get(BLOCKED_HEADER, "0")),
        )

    async def png(self, html: str, width: int, full_page: bool = True, scale: int = 1) -> Rendered:
        body = PngRequest(html=html, width=width, full_page=full_page, scale=scale)
        return self._rendered(await self._post("/png", body.model_dump()))

    async def scroll_pdf(self, html: str, width: int) -> Rendered:
        body = PdfRequest(html=html, width=width)
        return self._rendered(await self._post("/pdf", body.model_dump()))

    async def paged_pdf(self, html: str, page_size: str = "Letter") -> Rendered:
        body = PdfRequest(html=html, layout="paged", page_size=page_size)  # type: ignore[arg-type]
        return self._rendered(await self._post("/pdf", body.model_dump()))

    async def check(self, html: str) -> CheckResponse:
        response = await self._post("/check", CheckRequest(html=html).model_dump())
        return CheckResponse.model_validate(response.json())

    async def healthy(self) -> bool:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=TIMEOUT, transport=self._transport
            ) as client:
                return (await client.get("/health")).status_code == 200
        except httpx.HTTPError:
            return False


class UnavailableRenderer:
    """Stands in when no render service is configured, so callers take their fallback."""

    async def png(self, html: str, width: int, full_page: bool = True, scale: int = 1) -> Rendered:
        raise RenderUnavailable("no render service is configured (RENDER_URL is not set)")

    async def scroll_pdf(self, html: str, width: int) -> Rendered:
        raise RenderUnavailable("no render service is configured (RENDER_URL is not set)")

    async def paged_pdf(self, html: str, page_size: str = "Letter") -> Rendered:
        raise RenderUnavailable("no render service is configured (RENDER_URL is not set)")

    async def check(self, html: str) -> CheckResponse:
        raise RenderUnavailable("no render service is configured (RENDER_URL is not set)")

    async def healthy(self) -> bool:
        return False


def from_settings() -> Renderer:
    from src.core.settings import settings

    if not settings.RENDER_URL or not settings.RENDER_SHARED_SECRET:
        return UnavailableRenderer()
    return HttpRenderer(settings.RENDER_URL, settings.RENDER_SHARED_SECRET)

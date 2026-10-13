"""The render service: HTML in, PNG or PDF out, through a real Chromium.

It runs in its own container with none of the API's secrets, and only the API and worker
can reach it. Run with one uvicorn worker: the browser is per process, and concurrency is
limited inside it (config.MAX_CONCURRENT).
"""

import asyncio
import hmac
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Response

from . import capture, checks, config
from .browser import Browser, PageRejected
from .schemas import (
    BLOCKED_HEADER,
    HEIGHT_HEADER,
    SCALE_HEADER,
    TRUNCATED_HEADER,
    CheckRequest,
    CheckResponse,
    PdfRequest,
    PngRequest,
)

logger = logging.getLogger(__name__)

browser = Browser()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await browser.start()
    yield
    await browser.stop()


app = FastAPI(title="the-way render", lifespan=lifespan, docs_url=None, redoc_url=None)


def caller(x_render_secret: str = Header(default="")) -> None:
    if not config.SHARED_SECRET:
        raise HTTPException(503, "RENDER_SHARED_SECRET is not set; refusing to render")
    if not hmac.compare_digest(x_render_secret.encode(), config.SHARED_SECRET.encode()):
        raise HTTPException(401, "Wrong or missing X-Render-Secret")


async def _respond(
    make: Callable[[], Awaitable[capture.Rendered]], media_type: str
) -> Response:
    try:
        rendered = await asyncio.wait_for(make(), timeout=config.RENDER_TIMEOUT_SECONDS)
    except TimeoutError:
        raise HTTPException(504, "The page took too long to render and was stopped") from None
    except PageRejected as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception as exc:
        logger.exception("render failed")
        raise HTTPException(500, f"Could not render the page: {type(exc).__name__}") from None
    return Response(
        rendered.content,
        media_type=media_type,
        headers={
            HEIGHT_HEADER: str(rendered.height),
            TRUNCATED_HEADER: "1" if rendered.truncated else "0",
            SCALE_HEADER: f"{rendered.scale:.4f}",
            BLOCKED_HEADER: str(len(rendered.blocked)),
        },
    )


@app.get("/health")
async def health() -> dict[str, str]:
    if not browser.ready:
        raise HTTPException(503, "browser not running")
    return {"status": "ok"}


@app.post("/png", dependencies=[Depends(caller)])
async def png(request: PngRequest) -> Response:
    return await _respond(
        lambda: capture.png(browser, request.html, request.width, request.full_page, request.scale),
        "image/png",
    )


@app.post("/check", dependencies=[Depends(caller)])
async def check(request: CheckRequest) -> CheckResponse:
    try:
        measured = await asyncio.wait_for(
            checks.run(browser, request.html), timeout=config.RENDER_TIMEOUT_SECONDS
        )
    except TimeoutError:
        raise HTTPException(504, "The page took too long to check and was stopped") from None
    except PageRejected as exc:
        raise HTTPException(422, str(exc)) from None
    return CheckResponse.model_validate(measured)


@app.post("/pdf", dependencies=[Depends(caller)])
async def pdf(request: PdfRequest) -> Response:
    return await _respond(
        (lambda: capture.paged_pdf(browser, request.html, request.page_size))
        if request.layout == "paged"
        else (lambda: capture.scroll_pdf(browser, request.html, request.width)),
        "application/pdf",
    )

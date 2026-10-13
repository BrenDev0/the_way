"""One Chromium per process, a fresh context for every page.

Every page is treated as hostile: an agent wrote it, and it may carry text a user pasted.
So each one gets a context of its own (no cookies, storage or cache shared with any other
page), JavaScript off, and a network that answers only for inline data and Google Fonts --
the same allowlist the WeasyPrint exports use. A page cannot make this service reach into
its own network, the cloud's metadata address, or anything else.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from urllib.parse import urlparse

from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import Page, Playwright, Route, async_playwright

from . import config

logger = logging.getLogger(__name__)

# A meta refresh navigates even with scripts off. Aborted, it still leaves the page on
# Chromium's error page, and that is what would be rendered. Taken out before loading.
_META_REFRESH = re.compile(
    r"<meta\b[^>]*http-equiv\s*=\s*[\"']?\s*refresh\b[^>]*>", re.IGNORECASE
)

# Only what a page's web fonts need: Google's stylesheet and the font files it points at.
_FONT_RESOURCES = frozenset({"stylesheet", "font"})


class PageRejected(ValueError):
    """The page tried to leave itself; what is on screen is no longer the page."""


@dataclass
class Session:
    page: Page
    # addresses the page asked for and did not get
    blocked: list[str] = field(default_factory=list)


def allowed(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "data" or (
        parsed.scheme == "https" and parsed.hostname in config.ALLOWED_HOSTS
    )


async def _route(route: Route, session: Session) -> None:
    request = route.request
    url = request.url
    if url.startswith("data:"):
        await route.continue_()
        return
    if request.is_navigation_request() or not (
        allowed(url) and request.resource_type in _FONT_RESOURCES
    ):
        session.blocked.append(url)
        await route.abort("blockedbyclient")
        return
    # Fetched here rather than continued, so a redirect is seen and refused: an allowed
    # address must not be able to send the browser somewhere else.
    try:
        response = await route.fetch(
            max_redirects=0, timeout=config.FETCH_TIMEOUT_SECONDS * 1000
        )
    except Exception:  # noqa: BLE001 -- an unreachable font falls back, it does not fail the page
        await route.abort("failed")
        return
    if 300 <= response.status < 400:
        session.blocked.append(url)
        await route.abort("blockedbyclient")
        return
    await route.fulfill(response=response)


class Browser:
    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: PlaywrightBrowser | None = None
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(config.MAX_CONCURRENT)
        self._active = 0
        self._renders = 0

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        await self._launch()

    async def stop(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    @property
    def ready(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    async def _launch(self) -> None:
        assert self._playwright is not None
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:  # it is being replaced because it may be broken
                logger.warning("closing the old browser failed", exc_info=True)
        self._browser = await self._playwright.chromium.launch(args=config.CHROMIUM_ARGS)
        self._renders = 0

    async def _current(self) -> PlaywrightBrowser:
        async with self._lock:
            # Replaced when it crashed, or when it is due and no page is still using it.
            due = self._renders >= config.RESTART_AFTER and self._active == 0
            if not self.ready or due:
                await self._launch()
            assert self._browser is not None
            return self._browser

    @asynccontextmanager
    async def open(self, html: str, width: int, scale: int = 1) -> AsyncIterator[Session]:
        """The page loaded at `width` CSS pixels, its fonts in, ready to measure or capture.
        Its context is closed when the block ends, whatever happens inside."""
        async with self._slots:
            browser = await self._current()
            self._active += 1
            self._renders += 1
            context = await browser.new_context(
                viewport={"width": width, "height": config.SCREEN_HEIGHT_PX},
                device_scale_factor=scale,
                java_script_enabled=False,
                service_workers="block",
                accept_downloads=False,
            )
            try:
                page = await context.new_page()
                session = Session(page)
                await context.route("**/*", lambda route: _route(route, session))
                await page.set_content(
                    _META_REFRESH.sub("", html),
                    wait_until="load",
                    timeout=config.RENDER_TIMEOUT_SECONDS * 1000,
                )
                if page.url != "about:blank":
                    raise PageRejected("the page navigated away from itself")
                # Evaluated by Playwright, not the page: it works with the page's scripts off.
                await page.evaluate("document.fonts.ready.then(() => true)")
                yield session
            finally:
                self._active -= 1
                await context.close()

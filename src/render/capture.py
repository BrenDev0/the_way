"""Pages into PNG and single-page PDF, as Chromium shows them on a screen."""

import math
from dataclasses import dataclass

from src.exports.css import print_safe

from . import config
from .browser import Browser
from .print_css import (
    PAGED_VIEWPORT_WIDTH,
    PREPARE_SCROLL,
    PRINT_CSS,
    SCROLL_PAGE_CSS,
    SCROLL_WIDTH,
    with_css,
)

# The page's full height as laid out, read by Playwright with the page's scripts off.
_HEIGHT = "Math.ceil(Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0))"


@dataclass(frozen=True)
class Rendered:
    content: bytes
    # the page's laid-out height in CSS pixels
    height: int
    # True when the bottom was cut to stay within the size limit
    truncated: bool
    # below 1 when a tall page was shrunk to fit one PDF page
    scale: float
    blocked: list[str]


async def png(browser: Browser, html: str, width: int, full_page: bool, scale: int) -> Rendered:
    async with browser.open(html, width, scale) as session:
        height = int(await session.page.evaluate(_HEIGHT))
        shown = min(height, config.PNG_MAX_HEIGHT_PX) if full_page else config.SCREEN_HEIGHT_PX
        # Clipped to the viewport's width: content running off the side is a defect the
        # image should show as cut, not hide by making the image wider.
        content = await session.page.screenshot(
            type="png",
            full_page=full_page,
            clip={"x": 0, "y": 0, "width": width, "height": shown},
        )
        return Rendered(content, height, full_page and height > shown, 1.0, session.blocked)


async def scroll_pdf(browser: Browser, html: str, width: int = SCROLL_WIDTH) -> Rendered:
    """The whole document on one PDF page as tall as it is, for messaging apps -- the kit's
    output-documents scroll, rendered the way its render.js does."""
    # Printing resolves viewport units against the paper: on a 9000 px tall page a 100vh
    # hero would be 9000 px. They become pixels of the screen first, as for the exports.
    source = print_safe(html, screen_width=width, screen_height=config.SCREEN_HEIGHT_PX)
    source = with_css(source, PRINT_CSS + SCROLL_PAGE_CSS)
    async with browser.open(source, width) as session:
        page = session.page
        await page.evaluate(PREPARE_SCROLL)
        # Its print CSS lives in @media print, so measuring the screen measures a document
        # nobody will see: the PDF comes out short, with the close cut off. Measured in the
        # medium it is printed in.
        await page.emulate_media(media="print")
        height = int(await page.evaluate(_HEIGHT))
        scale = min(1.0, max(config.PDF_MIN_SCALE, config.PDF_MAX_PAGE_PX / max(height, 1)))
        page_height = min(math.ceil(height * scale), config.PDF_MAX_PAGE_PX)
        content = await page.pdf(
            width=f"{width * scale:.2f}px",
            # +2 px: a hairline must not push a second page
            height=f"{page_height + 2}px",
            scale=scale,
            print_background=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            # if anything still overflows, no ghost pages
            page_ranges="1",
        )
        return Rendered(content, height, height * scale > page_height + 2, scale, session.blocked)


async def paged_pdf(browser: Browser, html: str, page_size: str = "Letter") -> Rendered:
    """Paper pages, the way the kit's render.js makes a document's paginated PDF: a 900 px
    screen, its hardened print CSS, backgrounds printed (without them the dark cover comes
    out white), 11 mm margins."""
    # A box that scrolls sideways cannot on paper; its table would lose columns silently.
    source = print_safe(html, screen_width=PAGED_VIEWPORT_WIDTH, screen_height=config.SCREEN_HEIGHT_PX)
    source = with_css(source, PRINT_CSS)
    async with browser.open(source, PAGED_VIEWPORT_WIDTH) as session:
        page = session.page
        await page.evaluate("document.querySelectorAll('.rv').forEach(e => e.classList.remove('pre'))")
        content = await page.pdf(
            format=page_size,
            print_background=True,
            margin={"top": "11mm", "right": "11mm", "bottom": "11mm", "left": "11mm"},
            prefer_css_page_size=False,
        )
        height = int(await page.evaluate(_HEIGHT))
        return Rendered(content, height, False, 1.0, session.blocked)

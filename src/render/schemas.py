"""What callers send the render service and what comes back. Plain pydantic, so
src.render_client imports it without Playwright installed."""

from typing import Literal

from pydantic import BaseModel, Field

from . import config
from .print_css import SCROLL_WIDTH

WIDTH = Field(
    default=config.DEFAULT_WIDTH,
    ge=config.MIN_WIDTH,
    le=config.MAX_WIDTH,
    description="Viewport width in CSS pixels; the page's own breakpoints apply",
)


class PngRequest(BaseModel):
    html: str = Field(max_length=config.MAX_HTML_BYTES)
    width: int = WIDTH
    full_page: bool = True
    scale: int = Field(default=1, ge=1, le=2)


class PdfRequest(BaseModel):
    """One tall page with the whole document on it, unpaginated, for reading on a phone
    in a messaging app (the kit's scroll PDF)."""

    html: str = Field(max_length=config.MAX_HTML_BYTES)
    width: int = Field(default=SCROLL_WIDTH, ge=config.MIN_WIDTH, le=config.MAX_WIDTH)
    # 'paged' is the kit's paginated PDF instead (see capture.paged_pdf); width is unused
    layout: Literal["scroll", "paged"] = "scroll"
    page_size: Literal["Letter", "A4"] = "Letter"


class CheckRequest(BaseModel):
    html: str = Field(max_length=config.MAX_HTML_BYTES)


class Finding(BaseModel):
    check: str
    # the viewport width it was measured at
    width: int
    message: str
    examples: list[str] = []


class CheckResponse(BaseModel):
    findings: list[Finding]
    # addresses the page asked for and was refused
    blocked: list[str] = []


# Response headers carrying what the bytes alone do not say.
HEIGHT_HEADER = "X-Render-Height"
TRUNCATED_HEADER = "X-Render-Truncated"
SCALE_HEADER = "X-Render-Scale"
BLOCKED_HEADER = "X-Render-Blocked"

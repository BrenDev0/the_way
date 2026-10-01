"""HTML into PDF and PNG, with WeasyPrint.

WeasyPrint lays out HTML and CSS itself -- grid, flexbox, web fonts, inline SVG -- without
running a browser, which suits the pages BuildHtmlPage writes: its rules already forbid
scripts and draw every chart as SVG. It only makes PDFs, so a PNG is the PDF of the page's
screen layout, rasterised with pdfium and stitched into one image.

Two things make the result match what the page looked like on screen, where a plain
conversion clips: viewport units are resolved against a real screen first (css.py), and
content wider than the page is scaled down to fit it, the way a browser prints, rather
than running off the edge.

Imported lazily: WeasyPrint needs Pango from the operating system, and a machine without
it should still run everything else.
"""

import io
from dataclasses import dataclass
from urllib.parse import urlparse

from . import config
from .css import print_safe


class ExportUnavailable(RuntimeError):
    """The libraries rendering needs are not installed on this server."""


@dataclass(frozen=True)
class Rendered:
    content: bytes
    # below 1 when the page was scaled down so nothing ran off the edge
    zoom: float
    pages: int


def _weasyprint():
    try:
        import weasyprint
    except (ImportError, OSError) as exc:  # OSError: the package is there, Pango is not
        raise ExportUnavailable(str(exc)) from exc
    return weasyprint


def _check(url: str) -> None:
    """Only what a page is allowed to load: inline data and Google Fonts."""
    parsed = urlparse(url)
    allowed = parsed.scheme == "data" or (
        parsed.scheme == "https" and parsed.hostname in config.ALLOWED_HOSTS
    )
    if not allowed:
        raise ValueError(f"Not fetched while rendering: {url[:120]}")


def _fetcher():
    _weasyprint()
    from weasyprint.urls import URLFetcher

    class PageFetcher(URLFetcher):
        def fetch(self, url, headers=None):
            _check(url)
            return super().fetch(url, headers)

    # No redirects: an allowed address must not be able to send the server somewhere else.
    return PageFetcher(
        timeout=config.FETCH_TIMEOUT_SECONDS,
        allowed_protocols=("https", "data"),
        allow_redirects=False,
    )


def _right_edge(box, clip: float = float("inf")) -> float:
    """How far right anything visible in this box reaches. What an ancestor with overflow
    other than visible cuts off does not count: a decorative shape hung off the side of a
    clipped hero is meant to be cut, and must not shrink the whole page."""
    try:
        right = box.position_x + box.margin_width()
    except (AttributeError, TypeError):
        right = float("-inf")
    edge = min(right, clip)

    children = getattr(box, "children", None) or ()
    if children:
        try:
            visible = box.style["overflow"] == "visible"
        except (KeyError, TypeError):
            visible = True
        inner_clip = clip if visible else min(clip, right)
        for child in children:
            edge = max(edge, _right_edge(child, inner_clip))
    return edge


def _widest(document) -> float:
    widest = 0.0
    for page in document.pages:
        root = page._page_box
        for child in getattr(root, "children", ()):
            widest = max(widest, _right_edge(child))
    return widest


def _layout(html: str, media: str, width: float, height: float, margin: float):
    """Lays the page out at `width` x `height` CSS pixels, widening the layout (and so
    shrinking it onto the page) until nothing visible runs past the right margin.
    Returns the document and the zoom that puts it back on a page of the asked-for size."""
    weasyprint = _weasyprint()
    safety = weasyprint.CSS(string=config.SAFETY_CSS)
    source = print_safe(html, screen_width=width, screen_height=config.SCREEN_HEIGHT_PX)

    fetcher = _fetcher()
    zoom = 1.0
    document = None
    for _ in range(config.FIT_PASSES):
        page = weasyprint.CSS(
            string=f"@page {{ size: {width / zoom:.2f}px {height / zoom:.2f}px; "
            f"margin: {margin / zoom:.2f}px; }}"
        )
        document = weasyprint.HTML(string=source, url_fetcher=fetcher, media_type=media).render(
            stylesheets=[page, safety]
        )
        # all in layout pixels: the right margin's edge, and how far the content reaches
        available = (width - margin) / zoom
        needed = _widest(document)
        if needed <= available + 1 or zoom <= config.MIN_FIT_ZOOM:
            break
        # The zoom at which the content's width fits between the margins. The wider layout
        # reflows, so the next pass measures it again rather than trusting this.
        content = needed - margin / zoom
        zoom = max(config.MIN_FIT_ZOOM, (width - 2 * margin) / content)
    return document, zoom


def to_pdf(html: str, page_size: str = "A4", match_screen: bool = False) -> Rendered:
    """The page as a paginated PDF. By default it uses the page's print stylesheet -- what
    the page builder writes for exactly this -- and `match_screen` keeps the on-screen
    colours instead."""
    width, height = config.PAGE_SIZES_PX[page_size]
    margin = 0 if match_screen else config.PRINT_MARGIN_PX
    document, zoom = _layout(html, "screen" if match_screen else "print", width, height, margin)
    return Rendered(document.write_pdf(zoom=zoom), zoom, len(document.pages))


def to_png(
    html: str,
    width: int = config.PNG_DEFAULT_WIDTH,
    full_page: bool = True,
    scale: int = 1,
) -> Rendered:
    """The page as it looks on a screen `width` pixels wide, as one PNG. The page's own
    breakpoints apply, so 390 gives the mobile layout."""
    import pypdfium2
    from PIL import Image, ImageChops

    document, zoom = _layout(html, "screen", width, config.PNG_PAGE_HEIGHT_PX, 0)
    pdf = document.write_pdf(zoom=zoom)

    # pdf points are 1/72 in and css pixels 1/96 in
    raster = 96 / 72 * scale
    limit = config.PNG_MAX_HEIGHT_PX * scale
    pages = []
    height = 0
    for pdf_page in pypdfium2.PdfDocument(pdf):
        image = pdf_page.render(scale=raster).to_pil().convert("RGB")
        pages.append(image)
        height += image.height
        if height >= limit or not full_page:
            break

    canvas = Image.new("RGB", (pages[0].width, height), "white")
    top = 0
    for image in pages:
        canvas.paste(image, (0, top))
        top += image.height

    # The last page is mostly empty background: cut it off below the last content.
    background = canvas.getpixel((0, canvas.height - 1))
    content = ImageChops.difference(canvas, Image.new("RGB", canvas.size, background)).getbbox()
    bottom = content[3] + config.PNG_BOTTOM_PADDING_PX * scale if content else canvas.height
    if not full_page:
        bottom = config.SCREEN_HEIGHT_PX * scale
    canvas = canvas.crop((0, 0, canvas.width, min(bottom, canvas.height, limit)))

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return Rendered(out.getvalue(), zoom, 1)

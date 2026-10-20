import asyncio
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath

from pypdfium2 import PdfDocument

from src.assistants.context import ToolContext
from src.core.exceptions import ApplicationError
from src.core.tools.domain import Tool
from src.render.print_css import KIT_CORE_MARKER, SCROLL_WIDTH
from src.render_client import client as render_client
from src.render_client.ports import Renderer, RenderUnavailable

from . import config, render
from .tool_schemas import HtmlToPdf, HtmlToPng

UNAVAILABLE = (
    "PDF and PNG conversion is not available on this server (its rendering libraries are "
    "not installed). Tell the user plainly; the HTML file is still there to open."
)


SCROLL_UNAVAILABLE = (
    "The one-page scroll PDF needs the browser renderer, which is not available on this "
    "server right now ({reason}). Offer the user the paginated PDF (layout 'paged') instead."
)

MISSING_STYLES = (
    " WARNING: stylesheet(s) the page links could not be found in the project, so the "
    "output is missing their styles: {styles}. Fix the link (a path from the page, or "
    "project:<name>/<path>) and convert again."
)


MISSING_IMAGES = (
    " WARNING: {count} image(s) the page uses are NOT in it, because they could not be "
    "found in the project: {images}. Point each at an image file in the project by its "
    "path from the page (e.g. ../photos/cat.png), then convert again. Do not tell the user "
    "the images are included until a conversion reports none missing."
)


def _output(path: str, output_path: str | None, suffix: str) -> str:
    if output_path and output_path.strip("/"):
        return output_path.strip("/")
    return str(PurePosixPath(path.strip("/")).with_suffix(suffix))


def _scroll_output(path: str) -> str:
    """name.html -> name-scroll.pdf beside it, the kit's name for the scroll PDF."""
    source = PurePosixPath(path.strip("/"))
    return str(source.with_name(f"{source.stem}-scroll.pdf"))


def build(context: ToolContext, renderer: Renderer | None = None) -> dict[str, Tool]:
    files = context.files
    browser = renderer or render_client.from_settings()

    def weasyprint(make: Callable[[str], render.Rendered]) -> Callable[[str], Awaitable[render.Rendered]]:
        async def run(html: str) -> render.Rendered:
            return await asyncio.wait_for(
                asyncio.to_thread(make, html), timeout=config.RENDER_TIMEOUT_SECONDS
            )

        return run

    async def convert(
        project: str,
        path: str,
        output_path: str | None,
        suffix: str,
        content_type: str,
        make: Callable[[str], Awaitable[render.Rendered]],
    ) -> str:
        if not path.lower().endswith((".html", ".htm")):
            return f"'{path}' is not an .html file. Convert the HTML page, not its output."

        target = await files.project(project)
        _, raw = await files.read_bytes(target, path)
        # The renderers load nothing from an address, so the page's own stylesheets and
        # images go inside it. One that cannot be found is said plainly below: left out
        # silently, it was reported as fixed when the PDF had none.
        html, missing_styles = await files.embed_stylesheets(target, path, raw.decode("utf-8", errors="replace"))
        html, missing = await files.embed_images(target, path, html)

        try:
            rendered = await make(html)
        except render.ExportUnavailable:
            return UNAVAILABLE
        except RenderUnavailable as exc:
            return SCROLL_UNAVAILABLE.format(reason=exc)
        except TimeoutError:
            return f"Converting {target.name}/{path} took too long and was stopped."
        except ApplicationError:
            raise
        except Exception as exc:  # noqa: BLE001 -- a page that will not render is the model's to fix
            return f"Could not convert {target.name}/{path}: {type(exc).__name__}: {exc}"

        destination = _output(path, output_path, suffix)
        await files.write(target, destination, rendered.content, overwrite=True, content_type=content_type)

        notes = [f"{len(rendered.content):,} bytes"]
        if suffix == ".pdf":
            notes.append(f"{rendered.pages} page{'' if rendered.pages == 1 else 's'}")
        if rendered.zoom < 0.999:
            notes.append(
                f"scaled to {rendered.zoom:.0%} so content wider than the page fits instead "
                "of being cut off"
            )
        if rendered.note:
            notes.append(rendered.note)
        saved = f"Saved {target.name}/{destination} ({', '.join(notes)})."
        if missing_styles:
            saved += MISSING_STYLES.format(styles="; ".join(missing_styles))
        if missing:
            saved += MISSING_IMAGES.format(count=len(missing), images="; ".join(missing))
        return saved

    async def html_to_pdf(
        project: str,
        path: str,
        output_path: str | None = None,
        page_size: str = "A4",
        match_screen: bool = False,
        layout: str = "paged",
    ) -> str:
        if layout == "scroll":
            async def scroll(html: str) -> render.Rendered:
                done = await browser.scroll_pdf(html, SCROLL_WIDTH)
                note = None
                if done.scale < 0.999:
                    note = f"shrunk to {done.scale:.0%} to fit one page"
                if done.truncated:
                    note = "too long for one page: the bottom was cut off"
                return render.Rendered(done.content, 1.0, 1, note)

            return await convert(
                project, path, output_path or _scroll_output(path),
                ".pdf", "application/pdf", scroll,
            )
        paper = weasyprint(lambda html: render.to_pdf(html, page_size=page_size, match_screen=match_screen))

        async def paged(html: str) -> render.Rendered:
            # A kit document (it carries the kit's core layer) is paginated the way the
            # kit's own engine does it, in a browser with the kit's print CSS: WeasyPrint
            # printed its dark cover white. Every other page keeps the tuned WeasyPrint path.
            if KIT_CORE_MARKER not in html:
                return await paper(html)
            try:
                done = await browser.paged_pdf(html, page_size)
            except RenderUnavailable:
                made = await paper(html)
                fallback = "a kit document made with the fallback renderer; check its dark blocks"
                return render.Rendered(made.content, made.zoom, made.pages, made.note or fallback)
            return render.Rendered(done.content, 1.0, len(PdfDocument(done.content)), None)

        return await convert(project, path, output_path, ".pdf", "application/pdf", paged)

    async def html_to_png(
        project: str,
        path: str,
        output_path: str | None = None,
        width: int = config.PNG_DEFAULT_WIDTH,
        full_page: bool = True,
        scale: int = 1,
    ) -> str:
        fallback = weasyprint(lambda html: render.to_png(html, width=width, full_page=full_page, scale=scale))

        async def png(html: str) -> render.Rendered:
            # A real browser shows what a person sees; WeasyPrint is the fallback when the
            # browser service is not there, and the result says so.
            try:
                done = await browser.png(html, width, full_page, scale)
            except RenderUnavailable:
                made = await fallback(html)
                approximated = "made with the fallback renderer, which approximates a browser"
                return render.Rendered(made.content, made.zoom, made.pages, made.note or approximated)
            cut = "too tall: only the top of the page is in the image" if done.truncated else None
            return render.Rendered(done.content, 1.0, 1, cut)

        return await convert(project, path, output_path, ".png", "image/png", png)

    return {
        HtmlToPdf.__name__: Tool(schema=HtmlToPdf, handler=html_to_pdf),
        HtmlToPng.__name__: Tool(schema=HtmlToPng, handler=html_to_png),
    }

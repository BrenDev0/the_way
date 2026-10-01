import asyncio
from collections.abc import Callable
from pathlib import PurePosixPath

from src.core.exceptions import ApplicationError
from src.core.tools.context import ToolContext
from src.core.tools.domain import Tool
from src.projects.files import ProjectFiles

from . import config, render
from .tool_schemas import HtmlToPdf, HtmlToPng

UNAVAILABLE = (
    "PDF and PNG conversion is not available on this server (its rendering libraries are "
    "not installed). Tell the user plainly; the HTML file is still there to open."
)


def _output(path: str, output_path: str | None, suffix: str) -> str:
    if output_path and output_path.strip("/"):
        return output_path.strip("/")
    return str(PurePosixPath(path.strip("/")).with_suffix(suffix))


def build(context: ToolContext) -> dict[str, Tool]:
    files = ProjectFiles(
        context.session, context.organization_id, context.user_id, context.bucket_store
    )

    async def convert(
        project: str,
        path: str,
        output_path: str | None,
        suffix: str,
        content_type: str,
        make: Callable[[str], render.Rendered],
    ) -> str:
        if not path.lower().endswith((".html", ".htm")):
            return f"'{path}' is not an .html file. Convert the HTML page, not its output."

        target = await files.project(project)
        _, raw = await files.read_bytes(target, path)
        html = raw.decode("utf-8", errors="replace")

        try:
            rendered = await asyncio.wait_for(
                asyncio.to_thread(make, html), timeout=config.RENDER_TIMEOUT_SECONDS
            )
        except render.ExportUnavailable:
            return UNAVAILABLE
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
        return f"Saved {target.name}/{destination} ({', '.join(notes)})."

    async def html_to_pdf(
        project: str,
        path: str,
        output_path: str | None = None,
        page_size: str = "A4",
        match_screen: bool = False,
    ) -> str:
        return await convert(
            project, path, output_path, ".pdf", "application/pdf",
            lambda html: render.to_pdf(html, page_size=page_size, match_screen=match_screen),
        )

    async def html_to_png(
        project: str,
        path: str,
        output_path: str | None = None,
        width: int = config.PNG_DEFAULT_WIDTH,
        full_page: bool = True,
        scale: int = 1,
    ) -> str:
        return await convert(
            project, path, output_path, ".png", "image/png",
            lambda html: render.to_png(html, width=width, full_page=full_page, scale=scale),
        )

    return {
        HtmlToPdf.__name__: Tool(schema=HtmlToPdf, handler=html_to_pdf),
        HtmlToPng.__name__: Tool(schema=HtmlToPng, handler=html_to_png),
    }

"""CheckPage: the builder's revision pass, measured instead of reread.

Three kinds of check, each reported for the builder to fix:
- in a browser (the render service, src/render): sideways scroll, dropped CSS, off-token
  colours, contrast, the keyboard, accessibility -- at phone and desktop width;
- in the raw HTML (lexical.py): notes left in comments, the brand's forbidden words, any
  trace of another brand;
- by eye: screenshots of the page go back with the report, so the builder sees the page it
  made, not only measurements of it -- up to a set number per page.

When the service is not there, the raw-HTML checks still run and the builder falls back to
its read-through pass: a page is never blocked on the checker.
"""

import asyncio
import base64
import io
from contextvars import ContextVar, Token
from dataclasses import dataclass, field

from src.core.tools.domain import ToolImage, ToolOutput
from src.projects.files import ProjectFiles
from src.render.schemas import CheckResponse
from src.render_client.ports import Renderer, RenderUnavailable

from . import config, lexical

UNAVAILABLE = (
    "The browser checks did not run: the page checker is not available right now "
    "({reason}). Do the revision pass by reading the page instead, and say in your report "
    "that it was not measured in a browser."
)

SCREENSHOTS = (
    "\n[screenshots] Attached: the top of the page at 1440px (desktop) and at 375px (phone). "
    "Look at them as a visitor would -- hierarchy, spacing, anything overlapping, cut off, "
    "unreadable or off-brand -- and fix what you see, not only what was measured. "
    "{left} more screenshot(s) for this page."
)
NO_MORE_SCREENSHOTS = "\n[screenshots] None attached: this page has used its {limit}."


@dataclass
class PageRun:
    """What the checks know about the page being built, set for one BuildHtmlPage call."""

    library: str | None = None
    brand: str | None = None
    forbidden: list[str] = field(default_factory=list)
    own_colours: set[str] = field(default_factory=set)
    others: list[lexical.OtherBrand] = field(default_factory=list)
    screenshots_left: int = config.MAX_SCREENSHOTS_PER_PAGE


# Set by BuildHtmlPage around its builder: CheckPage runs inside that call, so it reads the
# run it belongs to. The object is shared, so screenshots spent are spent for the page.
_current: ContextVar[PageRun | None] = ContextVar("page_run", default=None)


def start(run: PageRun) -> Token:
    return _current.set(run)


def finish(token: Token) -> None:
    _current.reset(token)


def _browser_report(result: CheckResponse, missing: list[str]) -> list[str]:
    lines = []
    for finding in result.findings:
        lines.append(f"\n[{finding.check} @ {finding.width}px] {finding.message}")
        lines += [f"  - {example}" for example in finding.examples]
    if missing:
        lines.append(
            "\n[images] not found in the project, so they are missing from the page: "
            + "; ".join(missing)
        )
    if result.blocked:
        lines.append(
            "\n[network] the page asked for addresses a page may not load (only Google Fonts "
            "and inline data are allowed): " + "; ".join(url[:100] for url in result.blocked[:5])
        )
    return lines


def _lexical_report(raw: str, run: PageRun) -> list[str]:
    lines = []
    notes = lexical.comments(raw)
    if notes:
        lines.append(
            "\n[comments] HTML comments travel with the page to wherever it is published. "
            "Remove each one; anything still undecided goes on the page as a visible [TK]:"
        )
        lines += [f"  - <!-- {note[:120]} -->" for note in notes[:6]]

    text = lexical.visible_text(raw)
    found = lexical.occurrences(text, run.forbidden)
    if found:
        lines.append(
            f"\n[voice] {run.brand}'s voice.md lists these as words its public copy never uses. "
            "Rewrite each, unless voice.md allows it in exactly this case (read its rule):"
        )
        lines += [f"  - '{term}': {context}" for term, context in found.items()]

    if run.library:
        traces = lexical.other_brand_traces(raw, text, run.library, run.own_colours, run.others)
        if traces:
            lines.append(
                f"\n[other brand] This page is for {run.brand}, but carries another brand's "
                "traces -- remove each, and re-check any figure or product name that came "
                "with them:"
            )
            lines += [f"  - {trace}" for trace in traces]
    return lines


def _fit(png: bytes, keep_height: int) -> ToolImage:
    """The top of a screenshot, at a size a model reads without scaling it down itself."""
    from PIL import Image

    with Image.open(io.BytesIO(png)) as image:
        top = image.crop((0, 0, image.width, min(image.height, keep_height))).convert("RGB")
        top.thumbnail((config.SCREENSHOT_MAX_SIDE, config.SCREENSHOT_MAX_SIDE))
        out = io.BytesIO()
        top.save(out, format="JPEG", quality=80)
    return ToolImage(base64=base64.b64encode(out.getvalue()).decode("ascii"), mime_type="image/jpeg")


async def _screenshots(renderer: Renderer, html: str) -> tuple[ToolImage, ...]:
    shots = await asyncio.gather(
        renderer.png(html, width=config.DESKTOP_WIDTH),
        renderer.png(html, width=config.PHONE_WIDTH),
    )
    desktop, phone = shots
    return (
        await asyncio.to_thread(_fit, desktop.content, config.DESKTOP_KEEP_HEIGHT),
        await asyncio.to_thread(_fit, phone.content, config.PHONE_KEEP_HEIGHT),
    )


async def check_page(files: ProjectFiles, renderer: Renderer, project: str, path: str) -> str | ToolOutput:
    if not path.lower().endswith((".html", ".htm")):
        return f"'{path}' is not an .html file."
    run = _current.get() or PageRun()
    target = await files.project(project)
    _, data = await files.read_bytes(target, path)
    raw = data.decode("utf-8", errors="replace")
    # as the exports see it: images and linked stylesheets inside the page, since the
    # browser loads no addresses
    html, _unlinked = await files.embed_stylesheets(target, path, raw)
    html, missing = await files.embed_images(target, path, html)

    lines = _lexical_report(raw, run)
    # each raw-HTML group is one finding; the browser's are counted as it reports them
    count = sum(1 for line in lines if line.startswith("\n["))
    images: tuple[ToolImage, ...] = ()
    measured = False
    try:
        result = await renderer.check(html)
        measured = True
        count += len(result.findings)
        clean = not result.findings and not missing and not result.blocked
        lines = _browser_report(result, missing) + lines
        if run.screenshots_left >= 2:
            try:
                images = await _screenshots(renderer, html)
                run.screenshots_left -= len(images)
                lines.append(SCREENSHOTS.format(left=run.screenshots_left))
            except Exception:  # noqa: BLE001 -- a screenshot is extra; it never fails the check
                images = ()
        else:
            lines.append(NO_MORE_SCREENSHOTS.format(limit=config.MAX_SCREENSHOTS_PER_PAGE))
    except RenderUnavailable as exc:
        lines.insert(0, UNAVAILABLE.format(reason=exc))
    except ValueError as exc:
        lines.insert(0, f"The browser checks did not run: the page could not be checked: {exc}")

    if measured and clean and not count:
        head = (
            f"{target.name}/{path}: no findings at 375px or 1440px. It does not scroll sideways, "
            "every colour on screen is a token, nothing was dropped or failed to load, the "
            "keyboard reaches everything with a visible focus, and the raw HTML is clean."
        )
    else:
        head = f"{target.name}/{path}: {count} finding(s). Fix each with a targeted edit."
    text = "\n".join([head, *lines])
    return ToolOutput(text=text, images=images) if images else text

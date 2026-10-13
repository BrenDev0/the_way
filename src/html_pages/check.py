"""CheckPage: the builder's revision pass, measured in a browser instead of reread.

The render service (src/render) opens the page at phone and desktop width and reports what
a reading of the file cannot see. When the service is not there, the tool says so and the
builder falls back to its read-through pass: a page is never blocked on the checker.
"""

from src.projects.files import ProjectFiles
from src.render.schemas import CheckResponse
from src.render_client.ports import Renderer, RenderUnavailable

UNAVAILABLE = (
    "The page checker is not available right now ({reason}). Do the revision pass by "
    "reading the page instead, and say in your report that it was not measured."
)


def report(project: str, path: str, result: CheckResponse, missing: list[str]) -> str:
    if not result.findings and not missing:
        return (
            f"{project}/{path}: no findings at 375px or 1440px. It does not scroll sideways, "
            "every colour on screen is a token, and nothing was dropped or failed to load."
        )
    lines = [f"{project}/{path}: {len(result.findings)} finding(s). Fix each with a targeted edit."]
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
    return "\n".join(lines)


async def check_page(files: ProjectFiles, renderer: Renderer, project: str, path: str) -> str:
    if not path.lower().endswith((".html", ".htm")):
        return f"'{path}' is not an .html file."
    target = await files.project(project)
    _, raw = await files.read_bytes(target, path)
    # as the exports see it: images inside the page, since the browser loads no addresses
    html, missing = await files.embed_images(target, path, raw.decode("utf-8", errors="replace"))
    try:
        result = await renderer.check(html)
    except RenderUnavailable as exc:
        return UNAVAILABLE.format(reason=exc)
    except ValueError as exc:
        return f"The page could not be checked: {exc}"
    return report(target.name, path, result, missing)

"""The images an HTML page in a project uses, found and swapped.

The agent writes a page the natural way, pointing at an image by its path from the page:
<img src="../cat-mouse-merida/cat.png">. Nothing that shows the page can follow that --
the viewer has nothing to resolve it against, and the PDF renderer loads no addresses at
all. So when a page is saved, each such path becomes the image's signed link (links.py),
which works wherever the page is opened; and when it is exported, each link or path is
replaced by the image itself, as a data: URI, which is all the renderer takes. An image in
another project is named as project:<name>/<path> and is treated the same way.
"""

import base64
import posixpath
import re
from collections.abc import Awaitable, Callable
from urllib.parse import unquote, urlsplit

# The value of src (or href, for an SVG <image>) on the tags that show an image.
TAG_SOURCE = re.compile(
    r"""(?P<head><(?:img|source|image|input)\b[^>]*?\s(?:src|href|xlink:href)\s*=\s*)"""
    r"""(?P<quote>["'])(?P<value>.*?)(?P=quote)""",
    re.IGNORECASE | re.DOTALL,
)
# url(...) in a <style> block or a style attribute: a background, a mask.
CSS_URL = re.compile(r"""url\(\s*(?P<quote>["']?)(?P<value>[^"')]+?)(?P=quote)\s*\)""", re.IGNORECASE)

SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")

# An image in another of the user's projects: project:Borradores/fotos/gato.png. A path
# from the page cannot leave the page's own project, and a background worker's pages live
# in '.the_way' while the images the user wants on them live everywhere else.
PROJECT_REF = re.compile(r"^project:(?P<project>[^/]+)/(?P<path>.+)$", re.IGNORECASE)


def references(html: str) -> list[str]:
    """Every image address the page uses, each once, in order."""
    found: dict[str, None] = {}
    for match in TAG_SOURCE.finditer(html):
        found.setdefault(match["value"].strip(), None)
    for match in CSS_URL.finditer(html):
        found.setdefault(match["value"].strip(), None)
    return [value for value in found if value]


def replace(html: str, swaps: dict[str, str]) -> str:
    """The page with each address in `swaps` replaced; anything else left as it was."""
    if not swaps:
        return html

    def tag(match: re.Match) -> str:
        new = swaps.get(match["value"].strip())
        return match.group(0) if new is None else f'{match["head"]}{match["quote"]}{new}{match["quote"]}'

    def css(match: re.Match) -> str:
        new = swaps.get(match["value"].strip())
        return match.group(0) if new is None else f'url("{new}")'

    return CSS_URL.sub(css, TAG_SOURCE.sub(tag, html))


def project_path(page_path: str, address: str) -> str | None:
    """Where a relative address points inside the project, from the page at `page_path`.
    None for anything that is not a path in the project: a URL, data:, an anchor, or a
    path that climbs out of the project."""
    if not address or address.startswith(("#", "//")) or SCHEME.match(address):
        return None
    path = unquote(urlsplit(address).path)
    if not path:
        return None
    if path.startswith("/"):
        joined = path.lstrip("/")
    else:
        folder = posixpath.dirname(page_path.strip("/"))
        joined = posixpath.join(folder, path)
    normal = posixpath.normpath(joined)
    if normal in (".", "") or normal == ".." or normal.startswith("../"):
        return None
    return normal


def project_ref(address: str) -> tuple[str, str] | None:
    """(project name, path in it) for a project: address, None for anything else or for a
    path that climbs out of the project."""
    match = PROJECT_REF.match(address.strip())
    if not match:
        return None
    normal = posixpath.normpath(unquote(match["path"]).lstrip("/"))
    if normal in (".", "") or normal == ".." or normal.startswith("../"):
        return None
    return unquote(match["project"]).strip(), normal


def data_uri(content: bytes, content_type: str) -> str:
    return f"data:{content_type};base64,{base64.b64encode(content).decode('ascii')}"


async def swaps_for(
    addresses: list[str],
    resolve: Callable[[str], Awaitable[str | None]],
) -> dict[str, str]:
    """What each address becomes, for those `resolve` has an answer for."""
    swaps: dict[str, str] = {}
    for address in addresses:
        new = await resolve(address)
        if new is not None and new != address:
            swaps[address] = new
    return swaps

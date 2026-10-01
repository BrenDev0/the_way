"""Rewrites a page's CSS so what fits a screen also fits paper.

A browser has a viewport; a paged renderer has pages. The same declarations mean different
things in each, and these are the ones that turn a good-looking page into a clipped PDF:

- vh, vw (and dvh, svh, lvh, vmin, vmax) resolve against the page, not a screen. A hero at
  "min-height: 100vh" becomes a page of its own; at "height: 100vh" with overflow hidden,
  everything past the first page of it is cut off. They are turned into pixels of the
  screen the page was designed on, and a fixed height in them becomes a minimum, so the
  section grows with its content instead of clipping it.
- position: fixed repeats on every page, over the content. It is placed once, where it
  sits at the top of the screen; sticky, which pages cannot do, stays where it is.

Only <style> blocks and style="" attributes are touched -- never the page's text.
"""

import re

_STYLE_BLOCK = re.compile(r"(<style\b[^>]*>)(.*?)(</style\s*>)", re.IGNORECASE | re.DOTALL)
_STYLE_ATTRIBUTE = re.compile(r"""(\sstyle\s*=\s*)(["'])(.*?)\2""", re.IGNORECASE | re.DOTALL)

_VIEWPORT = r"(?:d|s|l)?v(?:h|w|min|max)\b"
_VIEWPORT_LENGTH = re.compile(r"(-?\d*\.?\d+)(d|s|l)?(vh|vw|vmin|vmax)\b", re.IGNORECASE)

# "height" and "max-height" only -- the lookbehind keeps min-height and line-height out
_HEIGHT_IN_VIEWPORT = re.compile(
    rf"(?<![\w-])(max-height|height)(\s*:\s*)([^;{{}}]*?{_VIEWPORT}[^;{{}}]*)",
    re.IGNORECASE,
)
_POSITION = re.compile(r"(?<![\w-])position(\s*:\s*)(fixed|sticky)\b", re.IGNORECASE)


def print_safe(html: str, screen_width: float, screen_height: float) -> str:
    def fix(css: str) -> str:
        return _fix_css(css, screen_width, screen_height)

    html = _STYLE_BLOCK.sub(lambda m: m.group(1) + fix(m.group(2)) + m.group(3), html)
    return _STYLE_ATTRIBUTE.sub(lambda m: m.group(1) + m.group(2) + fix(m.group(3)) + m.group(2), html)


def _fix_css(css: str, width: float, height: float) -> str:
    def height_rule(match: re.Match[str]) -> str:
        name, separator, value = match.groups()
        if name.lower() == "max-height":
            return f"max-height{separator}none"
        return f"min-height{separator}{value}"

    css = _HEIGHT_IN_VIEWPORT.sub(height_rule, css)
    css = _POSITION.sub(
        lambda m: f"position{m.group(1)}{'absolute' if m.group(2).lower() == 'fixed' else 'relative'}",
        css,
    )

    def pixels(match: re.Match[str]) -> str:
        amount, _, unit = match.groups()
        base = {"vh": height, "vw": width, "vmin": min(width, height), "vmax": max(width, height)}
        return f"{float(amount) * base[unit.lower()] / 100:g}px"

    return _VIEWPORT_LENGTH.sub(pixels, css)

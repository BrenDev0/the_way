# The page builder's rules allow web fonts from Google and nothing else from outside the
# page, so that is all the renderer fetches. Anything else -- a file:// path, an internal
# address, a tracking pixel -- is refused, so a page cannot make the server reach into
# its own network or disk.
ALLOWED_HOSTS = frozenset({"fonts.googleapis.com", "fonts.gstatic.com"})
FETCH_TIMEOUT_SECONDS = 10

# Rendering is CPU work in a thread; a page that takes longer than this is not a report.
RENDER_TIMEOUT_SECONDS = 120

# The screen a page was designed on. Viewport units are resolved against it before
# rendering: on paper "100vh" would mean a whole page, which turns a hero section into a
# page of its own and clips whatever was below it.
SCREEN_HEIGHT_PX = 900

# CSS pixels (1/96 in) for each paper size.
PAGE_SIZES_PX = {"A4": (793.7, 1122.5), "Letter": (816.0, 1056.0)}

# Page margin for a printed PDF. A PDF that keeps the screen look is full-bleed: the page's
# own padding is its margin, and a white frame around a coloured page looks broken.
PRINT_MARGIN_PX = 53  # 14 mm

# Content wider than the page is scaled down to fit, the way a browser prints. Past this
# the text would be too small to read, so the rest overflows instead.
MIN_FIT_ZOOM = 0.45
FIT_PASSES = 3

PNG_DEFAULT_WIDTH = 1440
# A long page is laid out as a column of tall pages and stitched back into one image.
PNG_PAGE_HEIGHT_PX = 8000
# Past this the image is too big to open comfortably; the top of the page is kept.
PNG_MAX_HEIGHT_PX = 40000
# Breathing room kept below the last content when trailing background is trimmed.
PNG_BOTTOM_PADDING_PX = 32

# Applied after the page's own styles. Nothing here changes how a page looks on screen; it
# only stops the ways a laid-out page goes wrong on paper.
SAFETY_CSS = """
html, body { height: auto !important; max-height: none !important; overflow: visible !important; }
img, video, canvas { max-width: 100%; }
pre, code { white-space: pre-wrap; overflow-wrap: anywhere; }
p, li, dd, dt, td, th, blockquote, figcaption, h1, h2, h3, h4, h5, h6 { overflow-wrap: break-word; }
h1, h2, h3, h4, h5, h6 { break-after: avoid; }
figure, img, svg, tr, blockquote, pre { break-inside: avoid; }
thead { display: table-header-group; }
"""

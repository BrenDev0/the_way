# The render service's limits. Read from the environment directly, not from
# src.core.settings: this container gets no database URL, bucket keys or provider keys, and
# those settings refuse to load without them.

import os

from src.exports.config import ALLOWED_HOSTS, PNG_MAX_HEIGHT_PX, SCREEN_HEIGHT_PX

__all__ = ["ALLOWED_HOSTS", "PNG_MAX_HEIGHT_PX", "SCREEN_HEIGHT_PX"]

# Callers prove who they are with this, in the X-Render-Secret header. Unset, every render
# is refused: the service fails closed rather than rendering for anyone who can reach it.
SHARED_SECRET = os.environ.get("RENDER_SHARED_SECRET", "")
SECRET_HEADER = "X-Render-Secret"

# A page that takes longer than this is not a page, it is a problem. Covers loading the
# HTML, its fonts and producing the output.
RENDER_TIMEOUT_SECONDS = float(os.environ.get("RENDER_TIMEOUT_SECONDS", "30"))
# Each font request gets its own, shorter limit, so one slow font cannot use the whole budget.
FETCH_TIMEOUT_SECONDS = 10

# Pages render one context each, side by side up to this many; the rest wait their turn.
# Each one is 150-300 MB of browser memory, which is what the container's limit is sized on.
MAX_CONCURRENT = int(os.environ.get("RENDER_MAX_CONCURRENT", "2"))
# The browser process is replaced after this many renders, so whatever it accumulates (or
# whatever a page managed to leave behind in it) does not live long.
RESTART_AFTER = int(os.environ.get("RENDER_RESTART_AFTER", "100"))

# Images are already embedded as data: URIs by ProjectFiles.embed_images, so a page with
# photos is large; past this it is not a page someone reads.
MAX_HTML_BYTES = 8 * 1024 * 1024

MIN_WIDTH = 320
MAX_WIDTH = 2560
DEFAULT_WIDTH = 1440

# A PDF page cannot be taller than 200 inches (14 400 pt, 19 200 CSS px). A taller page is
# scaled down to fit one, as a browser would; past this scale the text is unreadable, so
# the bottom is cut instead.
PDF_MAX_PAGE_PX = 19_200
PDF_MIN_SCALE = 0.25

# Chromium's own flags. /dev/shm in a container is 64 MB, which a large page fills and
# crashes on, so shared memory goes to /tmp instead.
CHROMIUM_ARGS = ["--disable-dev-shm-usage", "--disable-gpu", "--no-first-run"]

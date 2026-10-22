from .base import AppSettings


class RenderSettings(AppSettings):
    """What the render service reads. It renders HTML an agent wrote, so it is given none of
    the app's secrets: no database, no Redis, no bucket keys. Importing this loads nothing
    else, and every variable has a default -- an unset secret refuses every render."""

    # Callers prove who they are with this, in the X-Render-Secret header. Unset, every
    # render is refused: the service fails closed rather than rendering for anyone who can
    # reach it. Must be the same value the api and the worker send (shared.py).
    RENDER_SHARED_SECRET: str = ""
    # A page that takes longer than this is not a page, it is a problem. Covers loading the
    # HTML, its fonts and producing the output.
    RENDER_TIMEOUT_SECONDS: float = 30
    # Pages render one context each, side by side up to this many; the rest wait their turn.
    # Each one is 150-300 MB of browser memory, which is what the container's limit is sized on.
    RENDER_MAX_CONCURRENT: int = 2
    # The browser process is replaced after this many renders, so whatever it accumulates (or
    # whatever a page managed to leave behind in it) does not live long.
    RENDER_RESTART_AFTER: int = 100


settings = RenderSettings()

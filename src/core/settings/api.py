from typing import Literal

from src.core.exceptions import InternalServerError

from .base import AppSettings

SameSitePolicy = Literal["lax", "strict", "none"]


class ApiSettings(AppSettings):
    """What only the api reads: who may call it, how it limits them, how it signs people in
    and where its emailed links lead. Every one has a default, so the worker -- which loads
    the api's app -- starts without any of them."""

    # --- who may call it ---------------------------------------------------------------
    CORS_ALLOWED_ORIGINS: list[str] = []
    REQUEST_SIGNATURE_WINDOW_SECONDS: int = 30

    # --- rate limiting (fastapi/rate_limit.py) ---------------------------------------------
    # Per address, on the sign-in paths. Past the cap in one window the address is blocked
    # for the block time.
    RATE_LIMIT_MAX_REQUESTS: int = 20
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_BLOCK_SECONDS: int = 60 * 15
    # How many entries from the right of X-Forwarded-For the client is. Railway's edge sends
    # "<client>, <its proxy address>", so a request that reaches the API through it (the
    # desktop app) is 2. The web service calls over the private network and sends the
    # visitor's address alone, so its requests are 1 -- if it called the public URL they
    # would be 2 as well.
    PUBLIC_PROXY_HOPS: int = 2
    WEB_PROXY_HOPS: int = 1

    # --- the web session -----------------------------------------------------------------
    SESSION_COOKIE_NAME: str = "session"
    SESSION_COOKIE_SECURE: bool = True
    SESSION_COOKIE_SAMESITE: SameSitePolicy = "lax"
    SESSION_TTL_SECONDS: int = 60 * 60 * 24 * 7

    # --- the desktop app's sign-in -----------------------------------------------------------
    DESKTOP_SESSION_TTL_SECONDS: int = 60 * 60 * 24 * 30
    DESKTOP_LOGIN_WINDOW_SECONDS: int = 60 * 15
    DESKTOP_LOGIN_MAX_FAILURES_PER_EMAIL: int = 5
    DESKTOP_LOGIN_MAX_FAILURES_PER_IP: int = 30

    # --- where emailed links and notices point -----------------------------------------------
    # An invitation to an existing organization: the panel's page that takes ?token= and a
    # password. Needed only when an invitation is sent.
    INVITATION_ACCEPT_URL: str | None = None
    # An owner invitation from Xplorers, starting an organization: a page that takes ?token=
    # and a password. Needed only when an invitation is sent.
    OWNER_INVITATION_ACCEPT_URL: str | None = None
    # The public page with the desktop installers, where the app's "new version" notice
    # points. Unset, the panel's /download beside INVITATION_ACCEPT_URL is used.
    DESKTOP_DOWNLOAD_PAGE_URL: str | None = None

    def require_invitation_accept_url(self) -> str:
        if not self.INVITATION_ACCEPT_URL:
            raise InternalServerError(
                message="Unable to process request at this time",
                code="invitation_accept_url_not_configured",
            )
        return self.INVITATION_ACCEPT_URL

    def require_owner_invitation_accept_url(self) -> str:
        if not self.OWNER_INVITATION_ACCEPT_URL:
            raise InternalServerError(
                message="Unable to process request at this time",
                code="owner_invitation_accept_url_not_configured",
            )
        return self.OWNER_INVITATION_ACCEPT_URL


settings = ApiSettings()

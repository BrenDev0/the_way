import ipaddress

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from src.core.cache.ports import CacheStore
from src.core.schemas import ErrorResponse

RATE_LIMIT_COUNT_KEY = "rate_limit:count"
RATE_LIMIT_BLOCK_KEY = "rate_limit:block"


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def resolve_client_ip(request: Request, trusted_proxy_hops: int) -> str | None:
    """The address the request came from.

    Each trusted proxy appends the address it received the request from to X-Forwarded-For,
    so the real client is `trusted_proxy_hops` entries from the RIGHT. Anything to its left
    was written by the client and can be anything, which is why the left is never read.
    Without the header (local runs, a direct connection) the peer address is the answer.
    """
    forwarded = [part for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    if trusted_proxy_hops > 0 and len(forwarded) >= trusted_proxy_hops:
        return _valid_ip(forwarded[-trusted_proxy_hops])
    return request.client.host if request.client else None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Caps how often one address may call the listed paths: past `max_requests` in a window
    it is blocked for `block_seconds`. Every call counts, not only failures, so it also
    slows enumeration (register, login) that never fails outright. Keys hold the plain
    address, so the address the limiter sees can be read in Redis."""

    def __init__(
        self,
        app: ASGIApp,
        paths: frozenset[str],
        max_requests: int,
        window_seconds: int,
        block_seconds: int,
        trusted_proxy_hops: int,
    ) -> None:
        super().__init__(app)
        self.paths = paths
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.block_seconds = block_seconds
        self.trusted_proxy_hops = trusted_proxy_hops

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method != "POST" or request.url.path.rstrip("/") not in self.paths:
            return await call_next(request)

        client_ip = resolve_client_ip(request, self.trusted_proxy_hops)
        if client_ip is None:
            return self._error(403, "client_ip_unavailable", "Unable to identify the client")

        cache_store: CacheStore = request.app.state.cache_store
        block_key = f"{RATE_LIMIT_BLOCK_KEY}:{client_ip}"
        if await cache_store.get_bool(block_key):
            return self._limited()

        count_key = f"{RATE_LIMIT_COUNT_KEY}:{client_ip}"
        count = await cache_store.increment(count_key)
        if count == 1:
            await cache_store.expire(count_key, self.window_seconds)
        if count > self.max_requests:
            await cache_store.store_bool(block_key, True, self.block_seconds)
            return self._limited()

        return await call_next(request)

    def _limited(self) -> JSONResponse:
        return self._error(
            429,
            "request_rate_limited",
            "Too many requests. Please wait before trying again",
            headers={"Retry-After": str(self.block_seconds)},
        )

    @staticmethod
    def _error(status_code: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
        body = ErrorResponse(message=message, code=code).model_dump(by_alias=True)
        return JSONResponse(body, status_code=status_code, headers=headers)

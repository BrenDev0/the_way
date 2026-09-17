import hmac
import time
from hashlib import sha256

from starlette.requests import ClientDisconnect, Request

from src.core.exceptions import AuthenticationError
from src.core.settings import settings

SIGNATURE_HEADER = "X-Signature"
TIMESTAMP_HEADER = "X-Timestamp"


def build_signature(method: str, path: str, timestamp: str, body: bytes) -> str:
    canonical_request = b"\n".join(
        [
            method.upper().encode("utf-8"),
            path.encode("utf-8"),
            timestamp.encode("utf-8"),
            body,
        ]
    )
    return hmac.new(
        settings.REQUEST_SIGNING_SECRET.encode("utf-8"),
        canonical_request,
        sha256,
    ).hexdigest()


def build_signed_path(request: Request) -> str:
    if request.url.query:
        return f"{request.url.path}?{request.url.query}"
    return request.url.path


async def verify_request_signature(request: Request) -> None:
    signature = request.headers.get(SIGNATURE_HEADER)
    timestamp = request.headers.get(TIMESTAMP_HEADER)

    if not signature or not timestamp:
        raise AuthenticationError(
            message="Missing request signature",
            code="request_signature_missing",
        )

    try:
        sent_at = int(timestamp)
    except ValueError:
        raise AuthenticationError(
            message="Invalid request signature",
            code="request_signature_invalid",
        ) from None

    if abs(time.time() - sent_at) > settings.REQUEST_SIGNATURE_WINDOW_SECONDS:
        raise AuthenticationError(
            message="Request signature expired",
            code="request_signature_expired",
        )

    try:
        body = await request.body()
    except ClientDisconnect:
        raise AuthenticationError(
            message="Invalid request signature",
            code="request_signature_invalid",
        ) from None

    expected_signature = build_signature(
        method=request.method,
        path=build_signed_path(request),
        timestamp=timestamp,
        body=body,
    )
    if not hmac.compare_digest(expected_signature, signature):
        raise AuthenticationError(
            message="Invalid request signature",
            code="request_signature_invalid",
        )

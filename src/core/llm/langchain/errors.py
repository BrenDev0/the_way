"""Which provider errors are passing trouble, not a bad request.

Read by name and status code rather than by class: the OpenAI and Anthropic SDKs each
define their own RateLimitError, APITimeoutError... with the same names and meaning, and
neither has to be installed for the other to work.
"""

from typing import Any

from src.core.exceptions import ApplicationError

from ..domain import LLMUnavailable, UnavailableReason

DETAIL_CHARS = 300

QUOTA_CODES = frozenset({"insufficient_quota", "billing_hard_limit_reached", "billing_error"})
QUOTA_PHRASES = ("credit balance", "insufficient_quota", "exceeded your current quota", "billing")

TIMEOUTS = frozenset({"APITimeoutError", "DeadlineExceededError", "TimeoutException", "TimeoutError"})
UNREACHABLE = frozenset({"APIConnectionError", "TransportError", "NetworkError", "RemoteProtocolError"})


def unavailable(exc: BaseException) -> LLMUnavailable | None:
    """The error as an LLMUnavailable, or None when it is not one -- a bad request, a bug."""
    if isinstance(exc, ApplicationError):  # ours, not the provider's: it has a status_code too
        return None
    detail = str(exc).strip()[:DETAIL_CHARS]
    names = {cls.__name__ for cls in type(exc).__mro__}

    # before the connection errors: both SDKs' timeout is a kind of connection error
    if names & TIMEOUTS:
        return LLMUnavailable(UnavailableReason.TIMEOUT, detail)

    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        if names & UNREACHABLE:
            return LLMUnavailable(UnavailableReason.PROVIDER_ERROR, detail)
        return None

    code = _code(exc)
    if status == 429:
        reason = UnavailableReason.QUOTA if code in QUOTA_CODES else UnavailableReason.RATE_LIMIT
        return LLMUnavailable(reason, detail, _retry_after(exc))
    if status == 402 or code in QUOTA_CODES or (status == 400 and _mentions_quota(exc)):
        return LLMUnavailable(UnavailableReason.QUOTA, detail)
    if status in (401, 403):
        return LLMUnavailable(UnavailableReason.CREDENTIALS, detail)
    if status in (408, 504):
        return LLMUnavailable(UnavailableReason.TIMEOUT, detail, _retry_after(exc))
    if status >= 500:  # 529 is Anthropic's "overloaded"
        return LLMUnavailable(UnavailableReason.PROVIDER_ERROR, detail, _retry_after(exc))
    return None


def _code(exc: BaseException) -> str | None:
    """OpenAI puts the error code on the exception; Anthropic, in the body's error type."""
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        return code
    body: Any = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict):
            found = error.get("code") or error.get("type")
            return found if isinstance(found, str) else None
    return None


def _mentions_quota(exc: BaseException) -> bool:
    lowered = f"{exc} {getattr(exc, 'body', '')}".lower()
    return any(phrase in lowered for phrase in QUOTA_PHRASES)


def _retry_after(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get("retry-after")
        return max(0.0, float(value)) if value is not None else None
    except (TypeError, ValueError):  # an HTTP date, rarely sent by these providers
        return None

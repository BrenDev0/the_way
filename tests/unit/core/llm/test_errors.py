import pytest

from src.core.exceptions import InternalServerError
from src.core.llm.domain import LLMUnavailable, UnavailableReason
from src.core.llm.langchain.errors import unavailable


class Response:
    def __init__(self, headers=None):
        self.headers = headers or {}


def provider_error(name, status=None, code=None, body=None, headers=None, base=Exception):
    """An exception shaped like the OpenAI/Anthropic SDKs' -- matched by name and status."""
    cls = type(name, (base,), {})
    exc = cls(f"{name}: something")
    if status is not None:
        exc.status_code = status
        exc.response = Response(headers)
    exc.code = code
    exc.body = body
    return exc


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (provider_error("RateLimitError", 429, code="rate_limit_exceeded"), UnavailableReason.RATE_LIMIT),
        (provider_error("RateLimitError", 429, code="insufficient_quota"), UnavailableReason.QUOTA),
        (
            provider_error("BadRequestError", 400, body={"error": {"message": "Your credit balance is too low"}}),
            UnavailableReason.QUOTA,
        ),
        (provider_error("AuthenticationError", 401), UnavailableReason.CREDENTIALS),
        (provider_error("PermissionDeniedError", 403), UnavailableReason.CREDENTIALS),
        (provider_error("InternalServerError", 500), UnavailableReason.PROVIDER_ERROR),
        (provider_error("OverloadedError", 529), UnavailableReason.PROVIDER_ERROR),
        (provider_error("APIConnectionError"), UnavailableReason.PROVIDER_ERROR),
        (provider_error("APITimeoutError", base=type("APIConnectionError", (Exception,), {})), UnavailableReason.TIMEOUT),
        (TimeoutError("read timed out"), UnavailableReason.TIMEOUT),
    ],
)
def test_passing_provider_trouble_is_unavailable(exc, reason):
    found = unavailable(exc)

    assert isinstance(found, LLMUnavailable)
    assert found.reason is reason


def test_the_anthropic_quota_error_type_is_a_quota():
    exc = provider_error("RateLimitError", 429, body={"type": "error", "error": {"type": "billing_error"}})

    assert unavailable(exc).reason is UnavailableReason.QUOTA


def test_a_rate_limit_keeps_how_long_to_wait():
    exc = provider_error("RateLimitError", 429, headers={"retry-after": "20"})

    assert unavailable(exc).retry_after == 20.0


@pytest.mark.parametrize(
    "exc",
    [
        provider_error("BadRequestError", 400, body={"error": {"message": "invalid tool schema"}}),
        provider_error("NotFoundError", 404),
        ValueError("a bug"),
        # ours: it has a status_code, but it is not the provider's
        InternalServerError(code="llm_empty_response"),
    ],
)
def test_a_bad_request_or_a_bug_is_not(exc):
    assert unavailable(exc) is None

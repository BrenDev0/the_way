import time

import pytest
from starlette.requests import Request

from src.api import signing
from src.core.exceptions import AuthenticationError


def make_request(
    *,
    method: str = "POST",
    path: str = "/api/v1/auth/login",
    query: str = "",
    headers: dict[str, str] | None = None,
    body: bytes = b"",
) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query.encode("utf-8"),
        "root_path": "",
        "server": ("testserver", 80),
        "headers": [
            (k.lower().encode("utf-8"), v.encode("utf-8")) for k, v in (headers or {}).items()
        ],
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def signed_headers(*, method="POST", path="/api/v1/auth/login", body=b"", timestamp=None):
    timestamp = timestamp or str(int(time.time()))
    signature = signing.build_signature(
        method=method, path=path, timestamp=timestamp, body=body
    )
    return {signing.SIGNATURE_HEADER: signature, signing.TIMESTAMP_HEADER: timestamp}


class TestBuildSignature:
    def test_is_deterministic(self):
        args = {"method": "POST", "path": "/x", "timestamp": "100", "body": b"{}"}
        assert signing.build_signature(**args) == signing.build_signature(**args)

    @pytest.mark.parametrize(
        "changed",
        [
            {"method": "GET"},
            {"path": "/y"},
            {"timestamp": "101"},
            {"body": b'{"a":1}'},
        ],
    )
    def test_changes_when_any_component_changes(self, changed):
        base = {"method": "POST", "path": "/x", "timestamp": "100", "body": b"{}"}
        assert signing.build_signature(**base) != signing.build_signature(**{**base, **changed})

    def test_method_is_case_insensitive(self):
        base = {"path": "/x", "timestamp": "100", "body": b"{}"}
        assert signing.build_signature(method="post", **base) == (
            signing.build_signature(method="POST", **base)
        )


class TestBuildSignedPath:
    def test_path_without_query(self):
        assert signing.build_signed_path(make_request(path="/a/b")) == "/a/b"

    def test_query_is_included(self):
        request = make_request(path="/a/b", query="x=1&y=2")
        assert signing.build_signed_path(request) == "/a/b?x=1&y=2"


class TestVerifyRequestSignature:
    async def test_valid_signature_passes(self):
        body = b'{"email":"a@example.com"}'
        request = make_request(body=body, headers=signed_headers(body=body))

        await signing.verify_request_signature(request)

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {signing.SIGNATURE_HEADER: "abc"},
            {signing.TIMESTAMP_HEADER: "100"},
        ],
        ids=["neither", "timestamp-missing", "signature-missing"],
    )
    async def test_missing_headers_are_rejected(self, headers):
        with pytest.raises(AuthenticationError) as exc:
            await signing.verify_request_signature(make_request(headers=headers))
        assert exc.value.code == "request_signature_missing"

    async def test_non_numeric_timestamp_is_rejected(self):
        headers = {
            signing.SIGNATURE_HEADER: "abc",
            signing.TIMESTAMP_HEADER: "not-a-number",
        }
        with pytest.raises(AuthenticationError) as exc:
            await signing.verify_request_signature(make_request(headers=headers))
        assert exc.value.code == "request_signature_invalid"

    async def test_stale_timestamp_is_rejected(self):
        old = str(int(time.time()) - 3600)
        request = make_request(headers=signed_headers(timestamp=old))

        with pytest.raises(AuthenticationError) as exc:
            await signing.verify_request_signature(request)
        assert exc.value.code == "request_signature_expired"

    async def test_tampered_body_is_rejected(self):
        headers = signed_headers(body=b'{"amount":1}')
        request = make_request(body=b'{"amount":9999}', headers=headers)

        with pytest.raises(AuthenticationError) as exc:
            await signing.verify_request_signature(request)
        assert exc.value.code == "request_signature_invalid"

    async def test_signature_from_another_path_is_rejected(self):
        headers = signed_headers(path="/api/v1/other")
        request = make_request(path="/api/v1/auth/login", headers=headers)

        with pytest.raises(AuthenticationError) as exc:
            await signing.verify_request_signature(request)
        assert exc.value.code == "request_signature_invalid"

    async def test_query_string_is_covered_by_the_signature(self):
        headers = signed_headers(path="/api/v1/auth/login")
        request = make_request(path="/api/v1/auth/login", query="admin=true", headers=headers)

        with pytest.raises(AuthenticationError) as exc:
            await signing.verify_request_signature(request)
        assert exc.value.code == "request_signature_invalid"

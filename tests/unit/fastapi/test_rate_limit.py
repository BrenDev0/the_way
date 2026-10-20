import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from helpers import FakeCacheStore

from src.fastapi.rate_limit import RateLimitMiddleware

LOGIN = "/api/v1/auth/login"
MAX_REQUESTS = 3


def build_app(cache: FakeCacheStore, hops: int = 1) -> TestClient:
    app = FastAPI()
    app.state.cache_store = cache
    app.add_middleware(
        RateLimitMiddleware,
        paths={LOGIN: hops},
        max_requests=MAX_REQUESTS,
        window_seconds=60,
        block_seconds=900,
    )

    @app.post(LOGIN)
    async def login() -> dict[str, str]:
        return {"ok": "yes"}

    @app.post("/api/v1/other")
    async def other() -> dict[str, str]:
        return {"ok": "yes"}

    return TestClient(app)


def forwarded(ip: str) -> dict[str, str]:
    return {"x-forwarded-for": ip}


@pytest.fixture
def cache():
    return FakeCacheStore()


def test_the_address_the_proxy_appended_is_the_one_counted(cache):
    client = build_app(cache)
    client.post(LOGIN, headers=forwarded("203.0.113.7"))
    assert cache.data["rate_limit:count:203.0.113.7"] == 1


def test_entries_the_client_wrote_to_the_left_are_ignored(cache):
    client = build_app(cache)
    client.post(LOGIN, headers=forwarded("1.2.3.4, 203.0.113.7"))
    assert "rate_limit:count:203.0.113.7" in cache.data
    assert "rate_limit:count:1.2.3.4" not in cache.data


def test_two_hops_reads_the_second_entry_from_the_right(cache):
    client = build_app(cache, hops=2)
    client.post(LOGIN, headers=forwarded("203.0.113.7, 10.0.0.9"))
    assert "rate_limit:count:203.0.113.7" in cache.data


def test_railways_edge_shape_gives_the_visitor_not_its_proxy(cache):
    # What Railway sent in production: "<visitor>, <its proxy address>".
    client = build_app(cache, hops=2)
    client.post(LOGIN, headers=forwarded("187.190.46.204, 84.17.44.226"))
    client.post(LOGIN, headers=forwarded("200.68.172.74, 84.17.44.225"))
    assert set(cache.data) == {"rate_limit:count:187.190.46.204", "rate_limit:count:200.68.172.74"}


def test_a_different_address_has_its_own_count(cache):
    client = build_app(cache)
    for _ in range(MAX_REQUESTS + 1):
        client.post(LOGIN, headers=forwarded("203.0.113.7"))
    assert client.post(LOGIN, headers=forwarded("203.0.113.7")).status_code == 429
    assert client.post(LOGIN, headers=forwarded("198.51.100.2")).status_code == 200


def test_past_the_cap_the_address_is_blocked_with_retry_after(cache):
    client = build_app(cache)
    statuses = [client.post(LOGIN, headers=forwarded("203.0.113.7")).status_code for _ in range(MAX_REQUESTS + 2)]
    assert statuses == [200, 200, 200, 429, 429]
    blocked = client.post(LOGIN, headers=forwarded("203.0.113.7"))
    assert blocked.headers["retry-after"] == "900"
    assert blocked.json()["code"] == "request_rate_limited"
    assert cache.ttls["rate_limit:block:203.0.113.7"] == 900


def test_the_window_starts_at_the_first_request(cache):
    client = build_app(cache)
    client.post(LOGIN, headers=forwarded("203.0.113.7"))
    assert cache.ttls["rate_limit:count:203.0.113.7"] == 60


def test_other_paths_are_not_counted(cache):
    client = build_app(cache)
    for _ in range(MAX_REQUESTS + 2):
        assert client.post("/api/v1/other", headers=forwarded("203.0.113.7")).status_code == 200
    assert cache.data == {}


def test_without_the_header_the_peer_address_is_used(cache):
    client = build_app(cache)
    client.post(LOGIN)
    assert cache.data == {"rate_limit:count:testclient": 1}


def test_a_forwarded_entry_that_is_not_an_address_is_refused(cache):
    client = build_app(cache)
    response = client.post(LOGIN, headers=forwarded("not-an-ip"))
    assert response.status_code == 403
    assert response.json()["code"] == "client_ip_unavailable"

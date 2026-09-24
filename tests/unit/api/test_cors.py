import pytest
from starlette.testclient import TestClient

from src.api.main import app
from src.core.settings import Settings, settings

CONFIGURED = settings.CORS_ALLOWED_ORIGINS
STRANGER = "https://not-configured.example.invalid"

ALLOWED = CONFIGURED[0] if CONFIGURED else ""


def origins(raw: str, monkeypatch) -> list[str]:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", raw)
    return Settings().CORS_ALLOWED_ORIGINS  # type: ignore[call-arg]


def test_no_origins_are_allowed_by_default(monkeypatch):
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    assert Settings().CORS_ALLOWED_ORIGINS == []  # type: ignore[call-arg]


def test_a_json_list_parses(monkeypatch):
    assert origins('["https://a.example.com"]', monkeypatch) == ["https://a.example.com"]


def test_several_origins_parse(monkeypatch):
    assert origins('["https://a.example.com", "https://b.example.com"]', monkeypatch) == [
        "https://a.example.com",
        "https://b.example.com",
    ]


def test_an_empty_json_list_allows_nothing(monkeypatch):
    assert origins("[]", monkeypatch) == []


def test_a_bare_comma_list_fails_loudly_rather_than_silently(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://a.example.com,https://b.example.com")

    with pytest.raises(ValueError):
        Settings()  # type: ignore[call-arg]


@pytest.fixture
def client():
    if not CONFIGURED:
        pytest.skip("no CORS origins are configured in this environment")
    return TestClient(app)


def preflight(client, origin: str, method: str = "POST", headers: str = "content-type"):
    return client.options(
        "/api/v1/documents",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )


def test_a_configured_origin_passes_preflight(client):
    response = preflight(client, ALLOWED)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED


@pytest.mark.parametrize("origin", CONFIGURED)
def test_every_configured_origin_is_allowed(client, origin):
    assert preflight(client, origin).headers["access-control-allow-origin"] == origin


def test_an_unconfigured_origin_is_refused(client):
    response = preflight(client, STRANGER)

    assert "access-control-allow-origin" not in response.headers


def test_credentials_are_allowed_so_the_session_cookie_travels(client):
    response = preflight(client, ALLOWED)

    assert response.headers["access-control-allow-credentials"] == "true"


def test_the_origin_is_echoed_rather_than_wildcarded(client):
    response = preflight(client, ALLOWED)

    assert response.headers["access-control-allow-origin"] != "*"


def test_the_signing_headers_survive_preflight(client):
    response = preflight(client, ALLOWED, headers="x-signature,x-timestamp,content-type")

    allowed = response.headers["access-control-allow-headers"].lower()
    assert "x-signature" in allowed
    assert "x-timestamp" in allowed


def test_preflight_does_not_need_a_request_signature(client):
    response = preflight(client, ALLOWED)

    assert response.status_code == 200


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE"])
def test_the_methods_the_api_uses_are_allowed(client, method):
    response = preflight(client, ALLOWED, method=method)

    assert response.status_code == 200


def test_a_simple_request_carries_the_origin_back(client):
    response = client.get("/health", headers={"Origin": ALLOWED})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED

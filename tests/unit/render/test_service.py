"""The service's front door and the client the API uses, without a browser."""

import httpx
import pytest
from fastapi.testclient import TestClient

from src.render import config
from src.render_client.client import HttpRenderer, UnavailableRenderer
from src.render_client.ports import RenderUnavailable

app_module = pytest.importorskip("src.render.app", reason="Playwright is not installed")


def test_without_a_configured_secret_nothing_renders(monkeypatch):
    monkeypatch.setattr(config, "SHARED_SECRET", "")
    # no `with`: the lifespan, and so the browser, never starts; the refusal comes first
    response = TestClient(app_module.app).post("/png", json={"html": "<p>x</p>"})

    assert response.status_code == 503


def test_a_wrong_secret_is_refused(monkeypatch):
    monkeypatch.setattr(config, "SHARED_SECRET", "right")
    client = TestClient(app_module.app)

    assert client.post("/png", json={"html": "x"}).status_code == 401
    assert client.post("/pdf", json={"html": "x"}, headers={"X-Render-Secret": "wrong"}).status_code == 401


def test_a_width_outside_the_limits_is_refused(monkeypatch):
    monkeypatch.setattr(config, "SHARED_SECRET", "right")
    response = TestClient(app_module.app).post(
        "/png", json={"html": "x", "width": 10_000}, headers={"X-Render-Secret": "right"}
    )

    assert response.status_code == 422


def _renderer(handler) -> HttpRenderer:
    return HttpRenderer("http://render:8100", "s3cret", transport=httpx.MockTransport(handler))


async def test_the_client_sends_the_secret_and_reads_what_came_back():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Render-Secret"] == "s3cret"
        assert request.url.path == "/png"
        return httpx.Response(
            200,
            content=b"\x89PNG",
            headers={"X-Render-Height": "1234", "X-Render-Truncated": "1", "X-Render-Blocked": "2"},
        )

    rendered = await _renderer(handler).png("<p>x</p>", 390)

    assert rendered.content == b"\x89PNG"
    assert rendered.height == 1234
    assert rendered.truncated
    assert rendered.blocked == 2


async def test_a_service_that_is_down_is_unavailable_not_an_error_in_the_page():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(RenderUnavailable):
        await _renderer(down).png("<p>x</p>", 390)
    with pytest.raises(RenderUnavailable):
        await _renderer(lambda r: httpx.Response(503, text="browser not running")).scroll_pdf("x", 390)
    assert not await _renderer(down).healthy()


async def test_a_page_the_service_could_not_render_is_reported_as_the_pages_problem():
    renderer = _renderer(lambda r: httpx.Response(422, json={"detail": "the page navigated away from itself"}))

    with pytest.raises(ValueError, match="navigated away"):
        await renderer.png("<p>x</p>", 390)


async def test_with_no_service_configured_callers_get_unavailable():
    with pytest.raises(RenderUnavailable):
        await UnavailableRenderer().png("x", 390)

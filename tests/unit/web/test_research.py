"""WebResearch against a stand-in for Tavily's research API: start a job, poll it while it
answers 202, read the report once it answers 200."""

from uuid import uuid4

import httpx
import pytest
from helpers import FakeBucketStore

from src.core.tools.context import Credential, ToolContext
from src.web import config as web_config
from src.web import tools as web_tools


def context() -> ToolContext:
    return ToolContext(
        session=None,  # type: ignore[arg-type]
        organization_id=uuid4(),
        user_id=uuid4(),
        user_role="member",
        bucket_store=FakeBucketStore(),
        credentials={"tavily": Credential(secret="tvly-test")},
        llm_factory=None,  # type: ignore[arg-type]
    )


@pytest.fixture
def tavily(monkeypatch):
    seen: list[tuple[str, str, dict | None]] = []
    polls = {"left": 2}

    def handle(request: httpx.Request) -> httpx.Response:
        body = request.content and httpx.Response(200, content=request.content).json()
        seen.append((request.method, request.url.path, body or None))
        assert request.headers["Authorization"] == "Bearer tvly-test"
        if request.method == "POST":
            return httpx.Response(201, json={"request_id": "r1", "status": "pending"})
        if polls["left"]:
            polls["left"] -= 1
            return httpx.Response(202, json={"request_id": "r1", "status": "in_progress"})
        return httpx.Response(
            200,
            json={
                "request_id": "r1",
                "status": "completed",
                "content": "El mercado creció 12% [1].",
                "sources": [{"title": "Informe", "url": "https://example.com/informe"}],
            },
        )

    real = httpx.AsyncClient
    monkeypatch.setattr(
        web_tools.httpx, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handle), **kwargs)
    )
    monkeypatch.setattr(web_config, "RESEARCH_POLL_SECONDS", 0)
    return seen


async def test_research_is_started_polled_and_reported_with_its_sources(tavily):
    research = web_tools.build(context())["WebResearch"].handler

    report = await research(topic="mercado de CRM en México 2026", depth="pro")

    assert tavily[0] == ("POST", "/research", {"input": "mercado de CRM en México 2026", "model": "pro"})
    assert [path for _, path, _ in tavily[1:]] == ["/research/r1"] * 3
    assert report.startswith("El mercado creció 12% [1].")
    assert "[1] Informe -- https://example.com/informe" in report


def test_research_is_offered_with_the_other_web_tools_and_to_background_workers():
    from src.background import config as background_config

    assert {"WebSearch", "ExtractWebPages", "MapWebPages", "CrawlWebPages", "WebResearch"} <= set(
        web_tools.build(context())
    )
    assert "WebResearch" in background_config.TOOLS

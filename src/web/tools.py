import asyncio
import json

import httpx

from src.api_keys.domain import Provider
from src.core.tools.context import ToolContext
from src.core.tools.domain import Tool

from . import config
from .schemas import CrawlWebPages, ExtractWebPages, MapWebPages, WebResearch, WebSearch


class WebSearchError(Exception):
    pass


def _research_report(result: dict) -> str:
    """The research as the model should read it: the synthesis, then its sources -- the
    citations in the text are numbered against this list."""
    content = result.get("content")
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2)
    sources = [
        f"[{number}] {source.get('title') or source.get('url')} -- {source.get('url')}"
        for number, source in enumerate(result.get("sources") or [], 1)
    ]
    return text + ("\n\nSources:\n" + "\n".join(sources) if sources else "")


def available(context: ToolContext) -> bool:
    return str(Provider.TAVILY) in context.credentials


def build(context: ToolContext) -> dict[str, Tool]:
    """The web tools, or none when no Tavily key has been issued to this user."""
    credential = context.credentials.get(str(Provider.TAVILY))
    if credential is None:
        return {}

    headers = {"Authorization": f"Bearer {credential.secret}"}

    async def send(http: httpx.AsyncClient, method: str, endpoint: str, body: dict | None = None) -> httpx.Response:
        try:
            response = await http.request(method, f"{config.TAVILY_URL}/{endpoint}", json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise WebSearchError(f"the web search service could not be reached: {exc}") from exc

        if response.status_code == 401:
            raise WebSearchError(
                "the web search key was refused. Tell the user their web search key needs "
                "to be reissued by an owner or admin."
            )
        if response.is_error:
            raise WebSearchError(
                f"the web search service answered {response.status_code}: {response.text[:300]}"
            )
        return response

    async def call(endpoint: str, body: dict, timeout: float = config.TIMEOUT_SECONDS) -> str:
        async with httpx.AsyncClient(timeout=timeout) as http:
            response = await send(http, "POST", endpoint, body)
        return json.dumps(response.json(), ensure_ascii=False)

    async def web_search(query: str) -> str:
        return await call("search", {"query": query})

    async def map_web_pages(url: str) -> str:
        return await call("map", {"url": url})

    async def extract_web_pages(urls: list[str]) -> str:
        return await call("extract", {"urls": urls})

    async def crawl_web_pages(url: str, instructions: str) -> str:
        return await call(
            "crawl", {"url": url, "instructions": instructions}, config.CRAWL_TIMEOUT_SECONDS
        )

    async def web_research(topic: str, depth: str = "auto") -> str:
        """Starts the research job, then polls it: 202 while it works, 200 once it is
        completed or failed."""
        model = depth if depth in ("auto", "mini", "pro") else "auto"
        async with httpx.AsyncClient(timeout=config.TIMEOUT_SECONDS) as http:
            started = (await send(http, "POST", "research", {"input": topic, "model": model})).json()
            request_id = started.get("request_id")
            if not request_id:
                raise WebSearchError(f"the research service did not start a job: {json.dumps(started)[:300]}")

            waited = 0.0
            while True:
                response = await send(http, "GET", f"research/{request_id}")
                result = response.json()
                if response.status_code == 200:
                    break
                if waited >= config.RESEARCH_TIMEOUT_SECONDS:
                    return (
                        f"The research on '{topic}' was still running after "
                        f"{config.RESEARCH_TIMEOUT_SECONDS // 60} minutes and was abandoned. "
                        "Use WebSearch and ExtractWebPages instead, or narrow the topic."
                    )
                await asyncio.sleep(config.RESEARCH_POLL_SECONDS)
                waited += config.RESEARCH_POLL_SECONDS

        if result.get("status") != "completed":
            return f"The research on '{topic}' failed on the research service's side. Try WebSearch instead."
        return _research_report(result)

    return {
        WebSearch.__name__: Tool(schema=WebSearch, handler=web_search),
        WebResearch.__name__: Tool(schema=WebResearch, handler=web_research),
        MapWebPages.__name__: Tool(schema=MapWebPages, handler=map_web_pages),
        ExtractWebPages.__name__: Tool(schema=ExtractWebPages, handler=extract_web_pages),
        CrawlWebPages.__name__: Tool(schema=CrawlWebPages, handler=crawl_web_pages),
    }

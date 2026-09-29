import json

import httpx

from src.api_keys.domain import Provider
from src.core.tools.context import ToolContext
from src.core.tools.domain import Tool

from . import config
from .schemas import CrawlWebPages, ExtractWebPages, MapWebPages, WebSearch


class WebSearchError(Exception):
    pass


def available(context: ToolContext) -> bool:
    return str(Provider.TAVILY) in context.credentials


def build(context: ToolContext) -> dict[str, Tool]:
    """The web tools, or none when no Tavily key has been issued to this user."""
    credential = context.credentials.get(str(Provider.TAVILY))
    if credential is None:
        return {}

    async def call(endpoint: str, body: dict, timeout: float = config.TIMEOUT_SECONDS) -> str:
        async with httpx.AsyncClient(timeout=timeout) as http:
            try:
                response = await http.post(
                    f"{config.TAVILY_URL}/{endpoint}",
                    json=body,
                    headers={"Authorization": f"Bearer {credential.secret}"},
                )
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

    return {
        WebSearch.__name__: Tool(schema=WebSearch, handler=web_search),
        MapWebPages.__name__: Tool(schema=MapWebPages, handler=map_web_pages),
        ExtractWebPages.__name__: Tool(schema=ExtractWebPages, handler=extract_web_pages),
        CrawlWebPages.__name__: Tool(schema=CrawlWebPages, handler=crawl_web_pages),
    }

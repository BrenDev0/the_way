from pydantic import BaseModel, Field


class WebSearch(BaseModel):
    """Search the web and return ranked results with snippets and source URLs.

    Fast -- answer with this directly rather than backgrounding it. Use it for current
    facts, prices, news, or anything outside your training data."""

    query: str = Field(
        description="Search query, phrased the way you would type it into a search engine"
    )


class MapWebPages(BaseModel):
    """List the URL structure of a site without fetching any page content.

    Returns URLs only, so it is far cheaper and faster than CrawlWebPages. Use it to
    discover what exists on a domain before deciding what to extract or crawl."""

    url: str = Field(
        description="Root URL of the site to map, including scheme, for example 'https://example.com'"
    )


class ExtractWebPages(BaseModel):
    """Fetch the full text of specific web pages whose URLs you already have.

    Use after WebSearch or MapWebPages when a snippet is not enough. Time scales with the
    number of URLs: a handful is fine to run directly, but for roughly ten or more, start
    a background task instead so the conversation is not blocked."""

    urls: list[str] = Field(
        description="Full URLs to fetch, each including scheme, for example 'https://example.com/article'"
    )


class CrawlWebPages(BaseModel):
    """Crawl a website, following links and collecting page content guided by instructions.

    SLOW -- typically minutes. If you are the main assistant and the user is not waiting
    on this specific result, do not call this directly: call StartBackgroundTask and put
    the crawl target and instructions in its task instructions. If you are already running
    as a background worker, call this directly."""

    url: str = Field(description="Root URL to start crawling from, including scheme")
    instructions: str = Field(
        description="What to look for while crawling, in plain language, for example "
        "'collect every listing page with price and square footage'"
    )

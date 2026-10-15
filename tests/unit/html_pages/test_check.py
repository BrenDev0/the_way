import base64
import io
from types import SimpleNamespace

from PIL import Image

from src.core.tools.domain import ToolOutput
from src.html_pages import check, config
from src.html_pages.check import PageRun
from src.render.schemas import CheckResponse, Finding
from src.render_client.ports import Rendered, RenderUnavailable


async def check_page(*args):
    """The report's text, whether or not screenshots came with it."""
    result = await check.check_page(*args)
    return result.text if isinstance(result, ToolOutput) else result


def png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, format="PNG")
    return out.getvalue()


class FakeFiles:
    def __init__(self, html: str, missing: list[str] | None = None):
        self.html = html
        self.missing = missing or []

    async def project(self, name):
        return SimpleNamespace(name=name)

    async def read_bytes(self, project, path):
        return None, self.html.encode()

    async def embed_images(self, project, path, html):
        return html.replace("cat.png", "data:image/png;base64,AAAA"), self.missing

    async def embed_stylesheets(self, project, path, html):
        return html.replace('<link rel="stylesheet" href="core.css">', "<style>.core{}</style>"), []


class FakeRenderer:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.seen = result, error, None
        self.shots: list[int] = []

    async def png(self, html, width, full_page=True, scale=1):
        self.shots.append(width)
        return Rendered(content=png(width, 4000), height=4000)

    async def check(self, html):
        self.seen = html
        if self.error:
            raise self.error
        return self.result


async def test_findings_come_back_with_their_width_and_examples():
    renderer = FakeRenderer(CheckResponse(findings=[
        Finding(check="overflow", width=375, message="The page scrolls sideways", examples=["div.hero reaches 610px"]),
    ], blocked=["http://tracker.example/p.gif"]))

    text = await check_page(FakeFiles('<img src="cat.png">'), renderer, "Web", "p.html")

    assert "1 finding(s)" in text
    assert "[overflow @ 375px] The page scrolls sideways" in text
    assert "  - div.hero reaches 610px" in text
    assert "tracker.example" in text
    # the browser gets the page with its images inside, as the exports do
    assert "data:image/png;base64" in renderer.seen


async def test_a_clean_page_says_so():
    text = await check_page(FakeFiles("<p>x</p>"), FakeRenderer(CheckResponse(findings=[])), "Web", "p.html")

    assert "no findings" in text


async def test_without_the_service_the_builder_is_told_to_read_instead():
    renderer = FakeRenderer(error=RenderUnavailable("RENDER_URL is not set"))

    text = await check_page(FakeFiles("<p>x</p>"), renderer, "Web", "p.html")

    assert "not available" in text and "reading the page instead" in text


async def test_images_missing_from_the_project_are_reported():
    files = FakeFiles("<p>x</p>", missing=["fotos/gato.png"])

    text = await check_page(files, FakeRenderer(CheckResponse(findings=[])), "Web", "p.html")

    assert "fotos/gato.png" in text


async def test_only_html_is_checked():
    assert "not an .html file" in await check_page(FakeFiles(""), FakeRenderer(), "Web", "p.pdf")


def test_the_builder_has_the_checker():
    assert "CheckPage" in config.BUILDER_TOOLS


async def test_screenshots_go_back_with_the_report_until_the_page_has_used_its_allowance():
    renderer = FakeRenderer(CheckResponse(findings=[]))
    token = check.start(PageRun())
    try:
        first = await check.check_page(FakeFiles("<p>x</p>"), renderer, "Web", "p.html")
        second = await check.check_page(FakeFiles("<p>x</p>"), renderer, "Web", "p.html")
        third = await check.check_page(FakeFiles("<p>x</p>"), renderer, "Web", "p.html")
    finally:
        check.finish(token)

    assert isinstance(first, ToolOutput) and len(first.images) == 2
    assert renderer.shots[:2] == [config.DESKTOP_WIDTH, config.PHONE_WIDTH]
    assert "2 more screenshot(s)" in first.text
    assert isinstance(second, ToolOutput) and "0 more screenshot(s)" in second.text
    # the fourth was the last: the third check is text only
    assert isinstance(third, str) and "has used its 4" in third
    # each is cut to the top of the page and sized for a model to read
    with Image.open(io.BytesIO(base64.b64decode(first.images[1].base64))) as phone:
        assert max(phone.size) <= config.SCREENSHOT_MAX_SIDE
        assert phone.size[1] / phone.size[0] < 4000 / config.PHONE_WIDTH


async def test_the_raw_html_is_read_for_comments_forbidden_words_and_other_brands():
    from src.html_pages.lexical import OtherBrand

    html = (
        "<!-- TODO: confirm the price with Ana --><h1>Tu cotización</h1>"
        '<img src="project:Biblioteca/GRE/logo.png" alt="">'
    )
    run = PageRun(library="Biblioteca", brand="SLS", forbidden=["cotización"], others=[OtherBrand("GRE", ("GRE",))])
    token = check.start(run)
    try:
        text = await check_page(FakeFiles(html), FakeRenderer(CheckResponse(findings=[])), "Web", "p.html")
    finally:
        check.finish(token)

    assert "3 finding(s)" in text
    assert "<!-- TODO: confirm the price with Ana -->" in text
    assert "'cotización': Tu cotización" in text
    assert "GRE's library folder" in text


async def test_the_raw_html_is_read_even_without_the_browser():
    token = check.start(PageRun(brand="SLS", forbidden=["gratis"]))
    try:
        text = await check_page(
            FakeFiles("<p>Consulta gratis</p>"), FakeRenderer(error=RenderUnavailable("down")), "Web", "p.html"
        )
    finally:
        check.finish(token)

    assert "not available" in text
    assert "'gratis'" in text


async def test_linked_stylesheets_are_inside_the_page_the_browser_checks():
    renderer = FakeRenderer(CheckResponse(findings=[]))

    await check_page(FakeFiles('<link rel="stylesheet" href="core.css"><p>x</p>'), renderer, "Web", "p.html")

    assert "<style>.core{}</style>" in renderer.seen

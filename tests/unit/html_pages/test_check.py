from types import SimpleNamespace

from src.html_pages import config
from src.html_pages.check import check_page
from src.render.schemas import CheckResponse, Finding
from src.render_client.ports import RenderUnavailable


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


class FakeRenderer:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.seen = result, error, None

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

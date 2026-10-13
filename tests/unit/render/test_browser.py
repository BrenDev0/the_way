"""The render service against a real Chromium. Needs Playwright and its browser, which the
render image has (locally: `uv sync --group render` then `playwright install chromium`);
skipped without them."""

import asyncio
import io

import pytest

playwright = pytest.importorskip("playwright.async_api")

from PIL import Image
from pypdfium2 import PdfDocument

from src.render import capture, config
from src.render.browser import Browser


@pytest.fixture
async def browser():
    browser = Browser()
    try:
        await browser.start()
    except Exception as exc:  # noqa: BLE001 -- package installed, browser binary missing
        pytest.skip(f"Chromium is not installed here: {exc}")
    yield browser
    await browser.stop()


async def test_only_inline_data_and_font_hosts_are_fetched(browser):
    html = """<html><head>
    <link rel="stylesheet" href="https://evil.example/x.css">
    </head><body>
    <img src="http://169.254.169.254/latest/meta-data/">
    <img src="file:///etc/passwd">
    <img src="https://fonts.gstatic.com/not-a-font.png">
    <img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=">
    <iframe src="http://postgres:5432/"></iframe>
    </body></html>"""

    async with browser.open(html, 800) as session:
        blocked = session.blocked

    assert any("169.254.169.254" in url for url in blocked)
    assert any("evil.example" in url for url in blocked)
    assert any("postgres:5432" in url for url in blocked)
    # an allowed host is still refused for anything that is not a font or its stylesheet
    assert any("fonts.gstatic.com/not-a-font.png" in url for url in blocked)
    assert not any(url.startswith("data:") for url in blocked)


async def test_scripts_in_the_page_do_not_run(browser):
    html = "<body><script>document.body.dataset.ran = 'yes'</script></body>"

    async with browser.open(html, 800) as session:
        ran = await session.page.evaluate("document.body.dataset.ran || null")

    assert ran is None


async def test_a_meta_refresh_cannot_take_the_page_somewhere_else(browser):
    html = '<head><meta http-equiv="refresh" content="0;url=http://example.com/"></head><body><h1>Mine</h1></body>'

    async with browser.open(html, 800) as session:
        await asyncio.sleep(0.5)
        text = await session.page.inner_text("h1")
        url = session.page.url

    assert text == "Mine"
    assert url == "about:blank"


async def test_pages_share_no_state(browser):
    async with browser.open("<body>first</body>", 800) as first:
        await first.page.context.add_cookies(
            [{"name": "secret", "value": "1", "url": "https://fonts.googleapis.com"}]
        )
    async with browser.open("<body>second</body>", 800) as second:
        cookies = await second.page.context.cookies()

    assert cookies == []


async def test_a_page_stopped_for_time_leaves_the_browser_usable(browser):
    huge = "<body>" + "<div style='display:grid;grid-template-columns:repeat(40,1fr)'>" + "<span>x</span>" * 4000 + "</div>" * 50 + "</body>"

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(capture.png(browser, huge, 1440, True, 2), timeout=0.05)

    rendered = await capture.png(browser, "<body style='margin:0'><div style='height:1300px'></div></body>", 800, True, 1)
    assert Image.open(io.BytesIO(rendered.content)).size == (800, 1300)
    assert browser._active == 0


async def test_a_png_is_the_viewport_wide_even_when_content_runs_off_the_side(browser):
    html = "<body style='margin:0'><div style='width:900px;height:1200px;background:#c33'></div></body>"

    rendered = await capture.png(browser, html, 375, True, 1)

    image = Image.open(io.BytesIO(rendered.content))
    assert image.size == (375, 1200)
    assert rendered.height == 1200
    assert not rendered.truncated


async def test_a_png_taller_than_the_limit_keeps_the_top(browser, monkeypatch):
    monkeypatch.setattr(config, "PNG_MAX_HEIGHT_PX", 1000)
    html = "<body style='margin:0'><div style='height:3000px'></div></body>"

    rendered = await capture.png(browser, html, 400, True, 1)

    assert Image.open(io.BytesIO(rendered.content)).size == (400, 1000)
    assert rendered.truncated


async def test_the_scroll_pdf_is_one_page_as_tall_as_the_page(browser):
    html = """<body style='margin:0'>
    <section style='height:100vh;background:#123'></section>
    <div style='height:2000px;background:#eee'></div>
    <p>The end</p></body>"""

    rendered = await capture.scroll_pdf(browser, html, 390)

    pdf = PdfDocument(rendered.content)
    assert len(pdf) == 1
    # 100vh is the 900 px screen, not the paper: 900 + 2000 + the paragraph
    assert 2900 < rendered.height < 3100  # the kit print CSS sets body text at 10.5pt
    assert abs(pdf[0].get_width() * 96 / 72 - 390) <= 1  # Chrome rounds to whole points
    assert "The end" in pdf[0].get_textpage().get_text_range()


async def test_a_very_tall_scroll_pdf_is_shrunk_onto_one_page(browser):
    html = "<body style='margin:0'><div style='height:40000px'></div><p>Bottom</p></body>"

    rendered = await capture.scroll_pdf(browser, html, 400)

    pdf = PdfDocument(rendered.content)
    assert len(pdf) == 1
    assert rendered.scale < 0.5
    assert not rendered.truncated
    assert "Bottom" in pdf[0].get_textpage().get_text_range()


async def test_a_wide_table_in_the_scroll_becomes_cards_and_loses_no_column(browser):
    # the kit's paid-for defect: a scrolling .marco table lost its right-hand columns
    cells = "".join(f"<th>Col {i}</th>" for i in range(8))
    row = "".join(f"<td>v{i}</td>" for i in range(8))
    html = f"""<body style='margin:0'><div style='overflow-x:auto'><table style='min-width:900px'>
    <thead><tr>{cells}</tr></thead><tbody><tr>{row}</tr></tbody></table></div></body>"""

    rendered = await capture.scroll_pdf(browser, html)

    text = PdfDocument(rendered.content)[0].get_textpage().get_text_range()
    assert "v7" in text and "Col 7" in text  # the last column, with its header as label
    assert abs(PdfDocument(rendered.content)[0].get_width() * 96 / 72 - 440) <= 1


async def test_the_paged_pdf_prints_dark_blocks_and_paginates(browser):
    html = """<html><body style='margin:0'>
    <header class='cover' style='background:#0a0e1a;color:#fff;height:400px'>Portada</header>
    <div style='height:3000px'></div><p>Cierre</p></body></html>"""

    rendered = await capture.paged_pdf(browser, html, "Letter")

    pdf = PdfDocument(rendered.content)
    assert len(pdf) > 1
    assert round(pdf[0].get_width()) == 612  # Letter, in points
    # the cover's dark background is printed, not dropped
    image = pdf[0].render(scale=1).to_pil().convert("RGB")
    assert image.getpixel((image.width // 2, 80)) == (10, 14, 26)
    assert "Cierre" in "".join(p.get_textpage().get_text_range() for p in pdf)

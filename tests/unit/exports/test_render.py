"""Real rendering. Needs WeasyPrint's system libraries, which the Docker image has; skipped
on a machine without them."""

import io

import pytest

from src.exports import render

try:
    render._weasyprint()
except render.ExportUnavailable:
    pytest.skip("WeasyPrint's system libraries are not installed here", allow_module_level=True)

from PIL import Image
from pypdfium2 import PdfDocument

PAGE = """<!doctype html><html><head><style>
body { margin: 0; font-family: sans-serif; background: #f4efe6; }
.hero { height: 100vh; overflow: hidden; background: #123; color: white; padding: 40px; }
.wide { width: 1200px; background: #c33; height: 40px; }
</style></head><body>
<section class="hero"><h1>Informe</h1></section>
<div class="wide"></div>
<p>Final paragraph that must not be lost.</p>
</body></html>"""


def test_a_page_wider_than_the_paper_is_scaled_to_fit_rather_than_cut_off():
    pdf = render.to_pdf(PAGE, page_size="A4")

    assert pdf.content.startswith(b"%PDF")
    assert pdf.zoom < 0.7  # 1200px of content onto ~690px between the margins
    page = PdfDocument(pdf.content)[0]
    assert round(page.get_width()) == 595  # still A4, in points


def test_a_screen_height_hero_does_not_swallow_the_page():
    text = "".join(page.get_textpage().get_text_range() for page in PdfDocument(render.to_pdf(PAGE).content))

    assert "Final paragraph that must not be lost." in text


def test_a_png_is_the_width_asked_for_and_trimmed_to_its_content():
    png = render.to_png(PAGE, width=1440)
    image = Image.open(io.BytesIO(png.content))

    assert image.width == 1440
    assert 900 < image.height < 2000


def test_a_screenshot_is_one_screenful():
    image = Image.open(io.BytesIO(render.to_png(PAGE, width=1440, full_page=False, scale=2).content))

    assert image.size == (2880, 1800)


def test_the_renderer_fetches_nothing_but_inline_data_and_google_fonts():
    fetcher = render._fetcher()
    for url in ("http://169.254.169.254/latest/meta-data/", "file:///etc/passwd", "https://example.com/x.css"):
        with pytest.raises(ValueError):
            fetcher.fetch(url)


def test_a_page_that_links_web_fonts_still_renders():
    page = PAGE.replace(
        "<style>",
        '<link href="https://fonts.googleapis.com/css2?family=Inter&display=swap" rel="stylesheet">'
        '<link href="http://127.0.0.1:6379/x.css" rel="stylesheet"><style>',
    )

    assert render.to_pdf(page).content.startswith(b"%PDF")


def test_a_print_layout_weasyprint_cannot_paginate_falls_back_to_the_screen_layout(monkeypatch):
    layout = render._layout

    def failing_print(html, media, *args):
        if media == "print":
            raise AssertionError  # WeasyPrint's "assert not page_is_empty"
        return layout(html, media, *args)

    monkeypatch.setattr(render, "_layout", failing_print)

    pdf = render.to_pdf(PAGE)

    assert pdf.content.startswith(b"%PDF")
    assert pdf.note and "on-screen layout" in pdf.note
    assert render.to_pdf(PAGE, match_screen=True).note is None

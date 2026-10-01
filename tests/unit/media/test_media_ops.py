"""The PDF and image operations on real bytes."""

import io

import pytest
from PIL import Image
from pypdf import PdfReader

from src.media import image_ops, pdf_ops
from src.media.pages import PageSpecError, parse_pages


def png(width=200, height=100, color=(200, 30, 30, 255)) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (width, height), color).save(out, "PNG")
    return out.getvalue()


def pdf(pages: int) -> bytes:
    # a page per image, each a different width, so the order can be read back
    return pdf_ops.from_images([png(100 + 10 * n, 100) for n in range(pages)], "fit", 0)


def widths(data: bytes) -> list[int]:
    return [round(float(page.mediabox.width)) for page in PdfReader(io.BytesIO(data)).pages]


def test_pages_are_read_the_way_people_write_them():
    assert parse_pages("1-3, 5, 8-", 9) == [0, 1, 2, 4, 7, 8]
    assert parse_pages("3-1", 5) == [2, 1, 0]
    assert parse_pages("last", 4) == [3]
    assert parse_pages("", 3) == [0, 1, 2]
    with pytest.raises(PageSpecError):
        parse_pages("7", 3)


def test_pages_are_kept_reordered_dropped_and_rotated():
    source = pdf(5)
    first = widths(source)

    picked, count = pdf_ops.rearrange(source, keep="5,1-2")
    assert count == 3 and widths(picked) == [first[4], first[0], first[1]]

    dropped, count = pdf_ops.rearrange(source, remove="2-4")
    assert count == 2 and widths(dropped) == [first[0], first[4]]

    turned, _ = pdf_ops.rearrange(source, rotate=90, rotate_pages="1")
    rotations = [page.rotation for page in PdfReader(io.BytesIO(turned)).pages]
    assert rotations == [90, 0, 0, 0, 0]

    with pytest.raises(ValueError):
        pdf_ops.rearrange(source, remove="1-5")


def test_pdfs_merge_in_order_and_render_back_to_images():
    merged, count = pdf_ops.merge([pdf(2), pdf(3)])
    assert count == 5

    images = pdf_ops.to_images(merged, "2,5", 72, "png")
    assert [number for number, _ in images] == [2, 5]
    assert Image.open(io.BytesIO(images[0][1])).width == widths(merged)[1]


def test_images_land_on_paper_centred_and_landscape_when_wide():
    data = pdf_ops.from_images([png(1600, 900)], "A4", 28)
    page = PdfReader(io.BytesIO(data)).pages[0]
    assert float(page.mediabox.width) > float(page.mediabox.height)


def test_an_image_is_cropped_rotated_resized_and_padded_in_that_order():
    image = image_ops.transform(png(400, 200), crop_aspect="1:1")
    assert image.size == (200, 200)

    image = image_ops.transform(png(400, 200), rotate=90)
    assert image.size == (200, 400)  # clockwise, canvas turned with it

    image = image_ops.transform(png(400, 200), width=100)
    assert image.size == (100, 50)  # one side given: shape kept

    image = image_ops.transform(png(400, 200), width=100, height=100, fit="cover")
    assert image.size == (100, 100)

    image = image_ops.transform(png(400, 200), width=100, height=100, fit="contain", padding=10, background="#000")
    assert image.size == (120, 70)

    with pytest.raises(ValueError):
        image_ops.transform(png(), crop=(500, 500, 10, 10))


def test_formats_convert_and_jpeg_flattens_transparency_onto_white():
    transparent = png(color=(0, 0, 0, 0))
    jpeg = Image.open(io.BytesIO(image_ops.encode(Image.open(io.BytesIO(transparent)), "jpeg")))
    assert jpeg.format == "JPEG" and jpeg.getpixel((5, 5)) == (255, 255, 255)
    assert image_ops.inspect(transparent).transparent


def test_text_and_overlays_are_drawn_where_asked():
    written = image_ops.add_text(png(600, 300, (20, 20, 20, 255)), "OFERTA 2x1", position="top", box="black", size=40)
    top, bottom = written.crop((0, 0, 600, 100)), written.crop((0, 200, 600, 300))
    assert top.getextrema() != bottom.getextrema()  # something was drawn at the top, nothing at the bottom

    logo = png(100, 100, (0, 255, 0, 255))
    placed = image_ops.overlay(png(1000, 500, (0, 0, 0, 255)), logo, position="bottom-right", scale=0.1, margin=0)
    assert placed.getpixel((995, 495))[:3] == (0, 255, 0)
    assert placed.getpixel((5, 5))[:3] == (0, 0, 0)

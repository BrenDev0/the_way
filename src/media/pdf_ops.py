"""PDF work on bytes: read, rearrange, merge, and convert to and from images."""

import io
from dataclasses import dataclass

from pypdf import PdfReader, PdfWriter

from . import config
from .pages import parse_pages


@dataclass(frozen=True)
class PdfSummary:
    pages: int
    sizes: list[tuple[float, float]]  # points, per page
    metadata: dict[str, str]
    text: str
    encrypted: bool


def _reader(data: bytes) -> PdfReader:
    reader = PdfReader(io.BytesIO(data))
    # an owner password only restricts editing; an empty user password opens it
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("this PDF is password-protected and cannot be opened")
    return reader


def read(data: bytes, pages: str | None = None) -> PdfSummary:
    reader = _reader(data)
    chosen = parse_pages(pages, len(reader.pages))
    parts, used = [], 0
    for index in chosen:
        text = (reader.pages[index].extract_text() or "").strip()
        block = f"--- page {index + 1} ---\n{text or '(no text on this page: it may be a scan or an image)'}"
        if used + len(block) > config.MAX_TEXT_CHARS:
            parts.append(f"[... stopped at page {index + 1}: ask for fewer pages to read the rest]")
            break
        parts.append(block)
        used += len(block)
    metadata = {
        key.lstrip("/"): str(value)
        for key, value in (reader.metadata or {}).items()
        if value and key in ("/Title", "/Author", "/Subject", "/Creator", "/Producer", "/CreationDate")
    }
    return PdfSummary(
        pages=len(reader.pages),
        sizes=[(float(page.mediabox.width), float(page.mediabox.height)) for page in reader.pages],
        metadata=metadata,
        text="\n\n".join(parts),
        encrypted=reader.is_encrypted,
    )


def rearrange(
    data: bytes,
    keep: str | None = None,
    remove: str | None = None,
    rotate: int = 0,
    rotate_pages: str | None = None,
) -> tuple[bytes, int]:
    """Pages kept in the order `keep` lists them (all, by default), minus `remove`, with
    `rotate` degrees clockwise applied to `rotate_pages` (all kept pages, by default)."""
    if rotate % 90:
        raise ValueError("rotation must be a multiple of 90 degrees")
    reader = _reader(data)
    count = len(reader.pages)
    order = parse_pages(keep, count)
    dropped = set(parse_pages(remove, count)) if remove and remove.strip() else set()
    order = [index for index in order if index not in dropped]
    if not order:
        raise ValueError("that would leave the PDF with no pages")
    turned = set(parse_pages(rotate_pages, count)) if rotate_pages and rotate_pages.strip() else set(order)

    writer = PdfWriter()
    for index in order:
        page = writer.add_page(reader.pages[index])
        if rotate and index in turned:
            page.rotate(rotate)
    if reader.metadata:
        writer.add_metadata({k: v for k, v in reader.metadata.items() if isinstance(v, str)})
    return _written(writer), len(order)


def merge(documents: list[bytes]) -> tuple[bytes, int]:
    writer = PdfWriter()
    for data in documents:
        for page in _reader(data).pages:
            writer.add_page(page)
    return _written(writer), len(writer.pages)


def to_images(data: bytes, pages: str | None, dpi: int, image_format: str) -> list[tuple[int, bytes]]:
    """(page number, image bytes) for each page asked for."""
    import pypdfium2

    document = pypdfium2.PdfDocument(data)
    chosen = parse_pages(pages, len(document))
    if len(chosen) > config.MAX_RENDER_PAGES:
        raise ValueError(f"that is {len(chosen)} pages; render at most {config.MAX_RENDER_PAGES} per call")
    out = []
    for index in chosen:
        image = document[index].render(scale=max(36, min(dpi, config.MAX_RENDER_DPI)) / 72).to_pil()
        out.append((index + 1, _image_bytes(image, image_format)))
    return out


def from_images(images: list[bytes], page_size: str, margin_pt: float) -> bytes:
    """One page per image: the page the image's own size ('fit'), or A4/Letter with the
    image centred and scaled to fit inside the margins."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = config.MAX_IMAGE_PIXELS
    pages = []
    for data in images:
        image = Image.open(io.BytesIO(data))
        image.load()
        image = _flatten(image)
        if page_size in config.PAGE_SIZES_PT:
            # laid out at 150 dpi: sharp enough to print, small enough to send
            scale = 150 / 72
            width, height = (round(side * scale) for side in config.PAGE_SIZES_PT[page_size])
            if image.width > image.height and width < height:
                width, height = height, width  # a landscape picture gets a landscape page
            box = (width - 2 * round(margin_pt * scale), height - 2 * round(margin_pt * scale))
            if image.width > box[0] or image.height > box[1]:
                image.thumbnail(box)  # shrunk to fit, never blown up past its own size
            page = Image.new("RGB", (width, height), "white")
            page.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
            pages.append(page)
        else:
            pages.append(image)
    out = io.BytesIO()
    pages[0].save(out, "PDF", save_all=True, append_images=pages[1:], resolution=150)
    return out.getvalue()


def _flatten(image):
    """RGB on white -- a PDF page and a JPEG have no transparency."""
    from PIL import Image

    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, "white")
        canvas.paste(rgba, mask=rgba.split()[-1])
        return canvas
    return image.convert("RGB")


def _image_bytes(image, image_format: str) -> bytes:
    out = io.BytesIO()
    fmt = config.IMAGE_FORMATS.get(image_format, "PNG")
    (_flatten(image) if fmt == "JPEG" else image).save(out, fmt, **({"quality": 90} if fmt in ("JPEG", "WEBP") else {}))
    return out.getvalue()


def _written(writer: PdfWriter) -> bytes:
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()

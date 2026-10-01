"""Image work on bytes, with Pillow: inspect, transform, write text on, and lay one over another."""

import io
import os
from dataclasses import dataclass

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps

from . import config

Image.MAX_IMAGE_PIXELS = config.MAX_IMAGE_PIXELS

POSITIONS = ("top-left", "top", "top-right", "left", "center", "right", "bottom-left", "bottom", "bottom-right")


@dataclass(frozen=True)
class ImageSummary:
    width: int
    height: int
    format: str
    mode: str
    transparent: bool


def _open(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    # a phone photo stores "turn me" as a tag; apply it so width and height mean what you see
    return ImageOps.exif_transpose(image)


def inspect(data: bytes) -> ImageSummary:
    raw = Image.open(io.BytesIO(data))
    image = _open(data)
    return ImageSummary(
        width=image.width,
        height=image.height,
        format=(raw.format or "?").lower(),
        mode=image.mode,
        transparent=image.mode in ("RGBA", "LA") or "transparency" in image.info,
    )


def encode(image: Image.Image, image_format: str, quality: int = 90) -> bytes:
    fmt = config.IMAGE_FORMATS.get(image_format.lower(), "PNG")
    if fmt == "JPEG" and image.mode not in ("RGB", "L"):
        rgba = image.convert("RGBA")
        flat = Image.new("RGB", rgba.size, "white")
        flat.paste(rgba, mask=rgba.split()[-1])
        image = flat
    out = io.BytesIO()
    options = {"quality": max(1, min(quality, 100))} if fmt in ("JPEG", "WEBP") else {"optimize": True}
    image.save(out, fmt, **options)
    return out.getvalue()


def _color(value: str | None, fallback: str) -> tuple[int, int, int, int]:
    try:
        return ImageColor.getcolor(value or fallback, "RGBA")  # type: ignore[return-value]
    except ValueError as exc:
        raise ValueError(f"'{value}' is not a colour; use a name like 'white' or a hex like '#1d2433'") from exc


def transform(
    data: bytes,
    *,
    crop: tuple[int, int, int, int] | None = None,
    crop_aspect: str | None = None,
    rotate: float = 0,
    flip: str | None = None,
    width: int | None = None,
    height: int | None = None,
    fit: str = "contain",
    grayscale: bool = False,
    padding: int = 0,
    background: str | None = None,
) -> Image.Image:
    """Applied in the order a person would: crop, rotate, flip, resize, colour, pad."""
    image = _open(data)

    if crop:
        left, top, crop_width, crop_height = crop
        box = (max(0, left), max(0, top), min(image.width, left + crop_width), min(image.height, top + crop_height))
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError(f"that crop falls outside the {image.width}x{image.height} image")
        image = image.crop(box)
    elif crop_aspect:
        try:
            across, down = (float(part) for part in crop_aspect.replace("/", ":").split(":"))
        except ValueError as exc:
            raise ValueError(f"'{crop_aspect}' is not an aspect ratio like '16:9' or '1:1'") from exc
        target = across / down
        if image.width / image.height > target:
            new_width = round(image.height * target)
            image = image.crop(((image.width - new_width) // 2, 0, (image.width + new_width) // 2, image.height))
        else:
            new_height = round(image.width / target)
            image = image.crop((0, (image.height - new_height) // 2, image.width, (image.height + new_height) // 2))

    if rotate % 360:
        fill = _color(background, "#00000000" if image.mode == "RGBA" else "white")
        if image.mode not in ("RGBA", "RGB"):
            image = image.convert("RGBA")
        # Pillow turns counter-clockwise; people say "rotate 90" meaning clockwise
        image = image.rotate(-rotate, expand=True, fillcolor=fill if image.mode == "RGBA" else fill[:3])

    if flip in ("horizontal", "both"):
        image = ImageOps.mirror(image)
    if flip in ("vertical", "both"):
        image = ImageOps.flip(image)

    if width or height:
        target_width = width or round(image.width * (height or image.height) / image.height)
        target_height = height or round(image.height * (width or image.width) / image.width)
        if max(target_width, target_height) > config.MAX_OUTPUT_SIDE:
            raise ValueError(f"the result would be wider or taller than {config.MAX_OUTPUT_SIDE}px")
        size = (target_width, target_height)
        if fit == "cover":
            image = ImageOps.fit(image, size, Image.Resampling.LANCZOS)
        elif fit == "stretch" or not (width and height):
            image = image.resize(size, Image.Resampling.LANCZOS)
        else:  # contain: the whole picture inside the box, its shape kept
            image = ImageOps.contain(image, size, Image.Resampling.LANCZOS)

    if grayscale:
        image = ImageOps.grayscale(image) if image.mode != "RGBA" else _gray_keeping_alpha(image)

    if padding > 0:
        fill = _color(background, "white")
        base = image.convert("RGBA")
        padded = Image.new("RGBA", (base.width + 2 * padding, base.height + 2 * padding), fill)
        padded.alpha_composite(base, (padding, padding))
        image = padded

    return image


def _gray_keeping_alpha(image: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(image.convert("RGB")).convert("RGBA")
    gray.putalpha(image.getchannel("A"))
    return gray


def _anchor(position: str, box: tuple[int, int], item: tuple[int, int], margin: int) -> tuple[int, int]:
    if position not in POSITIONS:
        raise ValueError(f"position must be one of: {', '.join(POSITIONS)}")
    (width, height), (item_width, item_height) = box, item
    horizontal = "left" if "left" in position else "right" if "right" in position else "center"
    vertical = "top" if position.startswith("top") else "bottom" if position.startswith("bottom") else "middle"
    x = {"left": margin, "center": (width - item_width) // 2, "right": width - item_width - margin}[horizontal]
    y = {"top": margin, "middle": (height - item_height) // 2, "bottom": height - item_height - margin}[vertical]
    return x, y


def _font(style: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in config.FONTS.get(style, config.FONTS["sans"]):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def add_text(
    data: bytes,
    text: str,
    *,
    position: str = "bottom",
    size: int | None = None,
    color: str = "white",
    font: str = "sans-bold",
    box: str | None = None,
    box_opacity: float = 0.6,
    margin: int | None = None,
    max_width: float = 0.9,
) -> Image.Image:
    """Text on the picture, wrapped to fit, optionally on a translucent box so it reads
    over any background."""
    image = _open(data).convert("RGBA")
    size = size or max(12, image.width // 18)
    margin = image.width // 30 if margin is None else margin
    face = _font(font, size)

    pad = size // 2 if box else 0
    limit = image.width * max(0.2, min(max_width, 1.0)) - 2 * margin - 2 * pad
    content = "\n".join(_wrap(text, face, limit))
    # text in a corner lines up with that side; in the middle it is centred
    align = "left" if "left" in position else "right" if "right" in position else "center"

    draw = ImageDraw.Draw(image)
    left, top, right, bottom = draw.multiline_textbbox((0, 0), content, font=face, spacing=size // 4, align=align)
    text_size = (round(right - left), round(bottom - top))
    x, y = _anchor(position, image.size, (text_size[0] + 2 * pad, text_size[1] + 2 * pad), margin)

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    layer = ImageDraw.Draw(overlay)
    if box:
        red, green, blue, _ = _color(box, "black")
        layer.rounded_rectangle(
            (x, y, x + text_size[0] + 2 * pad, y + text_size[1] + 2 * pad),
            radius=pad // 2, fill=(red, green, blue, round(255 * max(0.0, min(box_opacity, 1.0)))),
        )
    layer.multiline_text(
        (x + pad - left, y + pad - top), content, font=face, fill=_color(color, "white"),
        spacing=size // 4, align=align,
    )
    return Image.alpha_composite(image, overlay)


def _wrap(text: str, face: ImageFont.FreeTypeFont | ImageFont.ImageFont, limit: float) -> list[str]:
    """Lines that really fit `limit` pixels, measured word by word in the font itself --
    an average letter width breaks lines that would have fit. The user's own line breaks
    are kept; a word too long for any line goes on one by itself."""
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if line and face.getlength(candidate) > limit:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines


def overlay(
    base_data: bytes,
    top_data: bytes,
    *,
    position: str = "bottom-right",
    scale: float = 0.2,
    opacity: float = 1.0,
    margin: int | None = None,
) -> Image.Image:
    """One image laid on another -- a logo in the corner, a watermark across the middle.
    `scale` is the overlay's width as a share of the base's."""
    base = _open(base_data).convert("RGBA")
    top = _open(top_data).convert("RGBA")
    target_width = max(1, round(base.width * max(0.01, min(scale, 1.0))))
    top = top.resize((target_width, max(1, round(top.height * target_width / top.width))), Image.Resampling.LANCZOS)
    if opacity < 1:
        alpha = top.getchannel("A").point(lambda value: round(value * max(0.0, opacity)))
        top.putalpha(alpha)
    margin = base.width // 30 if margin is None else margin
    base.alpha_composite(top, _anchor(position, base.size, top.size, margin))
    return base

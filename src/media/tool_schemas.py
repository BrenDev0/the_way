from typing import Literal

from pydantic import BaseModel, Field

from . import config

PROJECT = "Project name, exactly as ListProjects shows it"
OUTPUT = (
    "Where to save the result inside the project. Defaults to the source's name with "
    "'-editado' added, beside it -- the original is kept."
)
OVERWRITE = "Replace a file already at output_path, even the original. Only when the user asked for that."
PAGES = (
    "Pages as a person writes them, 1-based: '1-3,5', '8-' (to the end), '5-1' (backwards), "
    "'last'. Empty means every page."
)
Position = Literal["top-left", "top", "top-right", "left", "center", "right", "bottom-left", "bottom", "bottom-right"]
ImageFormat = Literal["png", "jpeg", "webp"]


class ReadPdf(BaseModel):
    """Read a PDF in a project: how many pages, their size, its metadata, and the text of
    the pages asked for. Use it before editing a PDF you have not seen, and to answer
    questions about one. A scanned page has no text to read."""

    project: str = Field(description=PROJECT)
    path: str = Field(description="The .pdf file")
    pages: str | None = Field(default=None, description=PAGES)


class EditPdfPages(BaseModel):
    """Make a new PDF from a PDF's pages: pick some (extract or split), drop some (delete),
    put them in another order, or rotate them. One call does any mix. For several separate
    pieces of one PDF -- a split -- call it once per piece."""

    project: str = Field(description=PROJECT)
    path: str = Field(description="The .pdf file")
    output_path: str | None = Field(default=None, description=OUTPUT)
    keep: str | None = Field(default=None, description=f"The pages to keep, in the order wanted. {PAGES}")
    remove: str | None = Field(default=None, description="Pages to leave out, written the same way.")
    rotate: Literal[0, 90, 180, 270] = Field(default=0, description="Degrees clockwise.")
    rotate_pages: str | None = Field(
        default=None, description="Which pages to rotate (original numbering). Empty means every kept page."
    )
    overwrite: bool = Field(default=False, description=OVERWRITE)


class MergePdfs(BaseModel):
    """Join PDFs, in the order given, into one -- all from the same project."""

    project: str = Field(description=PROJECT)
    paths: list[str] = Field(min_length=2, max_length=config.MAX_FILES_PER_CALL, description="The .pdf files, in order")
    output_path: str = Field(description="Where to save the joined PDF, ending in .pdf")
    overwrite: bool = Field(default=False, description=OVERWRITE)


class PdfToImages(BaseModel):
    """Turn PDF pages into images -- to post a page, preview one, or edit it as a picture.
    One image per page, saved in a folder."""

    project: str = Field(description=PROJECT)
    path: str = Field(description="The .pdf file")
    pages: str | None = Field(default=None, description=PAGES)
    output_folder: str | None = Field(
        default=None,
        description="Folder for the images, inside the project; each is named after the PDF and "
        "its page ('informe-p3.png'). Defaults to a folder named after the PDF, beside it.",
    )
    dpi: int = Field(
        default=config.DEFAULT_RENDER_DPI, ge=36, le=config.MAX_RENDER_DPI,
        description="Sharpness: 150 for the screen, 300 for print.",
    )
    image_format: ImageFormat = Field(default="png")


class ImagesToPdf(BaseModel):
    """Put images into one PDF, one per page, in the order given."""

    project: str = Field(description=PROJECT)
    paths: list[str] = Field(min_length=1, max_length=config.MAX_FILES_PER_CALL, description="The images, in page order")
    output_path: str = Field(description="Where to save the PDF, ending in .pdf")
    page_size: Literal["fit", "A4", "Letter"] = Field(
        default="fit",
        description="'fit' makes each page the size of its image; A4 or Letter puts each image "
        "centred on a sheet (turned landscape for a wide image).",
    )
    margin_mm: float = Field(default=10, ge=0, le=60, description="White margin round each image on A4/Letter.")
    overwrite: bool = Field(default=False, description=OVERWRITE)


class InspectImage(BaseModel):
    """An image's size in pixels, format and whether it has transparency."""

    project: str = Field(description=PROJECT)
    path: str = Field(description="The image")


class Crop(BaseModel):
    left: int = Field(ge=0, description="Pixels from the left edge")
    top: int = Field(ge=0, description="Pixels from the top edge")
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class TransformImage(BaseModel):
    """Exact, pixel-level edits to an image: crop, rotate, flip, resize, grayscale, add a
    border, or convert it to PNG/JPEG/WebP. Any mix in one call, applied in that order.

    For changes to what the picture SHOWS -- remove an object, change a background, restyle
    it -- use EditImage (AI) instead. This one never invents pixels."""

    project: str = Field(description=PROJECT)
    path: str = Field(description="The image")
    output_path: str | None = Field(
        default=None, description=f"{OUTPUT} Give a new extension to convert, e.g. 'logo.webp'."
    )
    crop: Crop | None = Field(default=None, description="A rectangle to keep. Use InspectImage first for the size.")
    crop_aspect: str | None = Field(
        default=None, description="Or: crop the centre to a shape, like '16:9', '1:1', '4:5', '9:16'."
    )
    rotate: float = Field(default=0, description="Degrees clockwise; any angle, the canvas grows to fit.")
    flip: Literal["horizontal", "vertical", "both"] | None = Field(default=None)
    width: int | None = Field(default=None, gt=0, le=config.MAX_OUTPUT_SIDE, description="New width in pixels")
    height: int | None = Field(default=None, gt=0, le=config.MAX_OUTPUT_SIDE, description="New height in pixels")
    fit: Literal["contain", "cover", "stretch"] = Field(
        default="contain",
        description="With both width and height: 'contain' fits the whole image inside, 'cover' fills "
        "the box exactly and trims the overflow, 'stretch' distorts it to the box. Give only one of "
        "width or height to scale and keep the shape.",
    )
    grayscale: bool = Field(default=False)
    padding: int = Field(default=0, ge=0, le=2000, description="A border this many pixels wide all round.")
    background: str | None = Field(
        default=None, description="Colour for the border and for corners a rotation opens up: 'white', '#0f172a', ..."
    )
    image_format: ImageFormat | None = Field(
        default=None, description="Output format; by default the output_path's extension, else the source's."
    )
    quality: int = Field(default=90, ge=1, le=100, description="For JPEG and WebP: lower is smaller and blurrier.")
    overwrite: bool = Field(default=False, description=OVERWRITE)


class AddTextToImage(BaseModel):
    """Write text on an image -- a title, a caption, a price, a call to action -- wrapped to
    fit, optionally on a translucent box so it reads over any picture."""

    project: str = Field(description=PROJECT)
    path: str = Field(description="The image")
    text: str = Field(min_length=1, max_length=2000, description="The words; line breaks are kept")
    output_path: str | None = Field(default=None, description=OUTPUT)
    position: Position = Field(default="bottom")
    size: int | None = Field(default=None, ge=6, le=1000, description="Letter height in pixels; about 1/18 of the width by default.")
    color: str = Field(default="white", description="Text colour: a name or a hex like '#ffcc00'")
    font: Literal["sans", "sans-bold", "serif"] = Field(default="sans-bold")
    box: str | None = Field(default=None, description="A colour for a box behind the text, e.g. 'black'. None for no box.")
    box_opacity: float = Field(default=0.6, ge=0, le=1)
    margin: int | None = Field(default=None, ge=0, description="Distance from the edge in pixels.")
    max_width: float = Field(default=0.9, ge=0.2, le=1, description="Widest the text may run, as a share of the image width.")
    overwrite: bool = Field(default=False, description=OVERWRITE)


class OverlayImage(BaseModel):
    """Lay one image over another -- a logo in a corner, a watermark across the middle, a
    badge on a product shot. Both must be in the same project."""

    project: str = Field(description=PROJECT)
    path: str = Field(description="The image underneath")
    overlay_path: str = Field(description="The image laid on top (a PNG with transparency works best)")
    output_path: str | None = Field(default=None, description=OUTPUT)
    position: Position = Field(default="bottom-right")
    scale: float = Field(default=0.2, gt=0, le=1, description="The overlay's width as a share of the image's: 0.2 is a fifth.")
    opacity: float = Field(default=1.0, ge=0, le=1, description="0.3 makes a faint watermark")
    margin: int | None = Field(default=None, ge=0, description="Distance from the edge in pixels")
    overwrite: bool = Field(default=False, description=OVERWRITE)

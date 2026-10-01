from typing import Literal

from pydantic import BaseModel, Field

PROJECT = "Project name, exactly as ListProjects shows it"
SOURCE = "The .html file to convert, for example 'reportes/ventas-q3.html'"


class HtmlToPdf(BaseModel):
    """Convert an HTML page in a project into a PDF, saved next to it.

    When the user asks for a report, document or page as a PDF, build it as HTML first with
    BuildHtmlPage, then convert it with this -- never hand-write a PDF any other way. The
    converter fixes the usual screen-to-paper problems itself (screen-height sections,
    content wider than the paper), scaling the page down to fit rather than cutting it off.
    An existing file at the output path is replaced."""

    project: str = Field(description=PROJECT)
    path: str = Field(description=SOURCE)
    output_path: str | None = Field(
        default=None,
        description="Where to save the PDF inside the project. Defaults to the same name "
        "with .pdf, beside the HTML.",
    )
    page_size: Literal["A4", "Letter"] = Field(
        default="A4", description="Paper size. Letter for the US and Canada, A4 elsewhere."
    )
    match_screen: bool = Field(
        default=False,
        description="False (the default) prints with the page's print styles: white paper, "
        "dark ink, margins -- right for a document someone will print or read as one. True "
        "keeps the on-screen look, colours and backgrounds edge to edge -- right for a "
        "deck-like or branded piece meant to be viewed, not printed.",
    )


class HtmlToPng(BaseModel):
    """Convert an HTML page in a project into a PNG image of how it looks on screen, saved
    next to it.

    When the user asks for a page, report or graphic as an image, build it as HTML first
    with BuildHtmlPage, then convert it with this. An existing file at the output path is
    replaced."""

    project: str = Field(description=PROJECT)
    path: str = Field(description=SOURCE)
    output_path: str | None = Field(
        default=None,
        description="Where to save the PNG inside the project. Defaults to the same name "
        "with .png, beside the HTML.",
    )
    width: int = Field(
        default=1440,
        ge=320,
        le=2560,
        description="Screen width in pixels. 1440 for desktop, 768 for a tablet, 390 for a "
        "phone -- the page's own mobile layout is used at narrow widths.",
    )
    full_page: bool = Field(
        default=True,
        description="True captures the whole page top to bottom; false only the first "
        "screenful (900 px), like a screenshot.",
    )
    scale: int = Field(
        default=1,
        ge=1,
        le=2,
        description="2 for a sharp image on high-density screens or slides, at four times "
        "the file size.",
    )

from typing import Literal

from pydantic import BaseModel, Field

from . import config

PROJECT = "Project to save the images in, exactly as ListProjects shows it"
MODEL = (
    "gpt-image-2.5-flare (fast, the default -- everyday images, social content, drafts) or "
    "gpt-image-2.5-sunburst (most detail and style, best for a hero image or careful edits). "
    "The user picks the final model when they approve, so this is your suggestion."
)

Size = Literal["auto", "1024x1024", "1536x1024", "1024x1536"]
Quality = Literal["auto", "low", "medium", "high", "xhigh", "max"]
Background = Literal["auto", "opaque", "transparent"]
Format = Literal["png", "jpeg", "webp"]


class ImageSpec(BaseModel):
    prompt: str = Field(
        description="Everything the image must show, in detail: subject, composition, style, "
        "lighting, colours, any exact text to render in quotes, and what to avoid."
    )
    output_path: str = Field(
        description="Where to save it inside the project, with the extension matching "
        "output_format -- for example 'campana/banner-hero.png'."
    )
    size: Size = Field(
        default="auto",
        description="1024x1024 square, 1536x1024 landscape, 1024x1536 portrait, or auto.",
    )
    quality: Quality = Field(default="auto", description="Higher costs more and takes longer.")
    background: Background = Field(
        default="auto",
        description="'transparent' for a logo, icon or cut-out asset (png or webp only).",
    )
    output_format: Format = Field(default="png")


class GenerateImages(BaseModel):
    """Generate images from text with OpenAI's GPT Image 2.5 and save them in a project.

    It spends the user's money, so the user approves it -- even inside a background task,
    which waits for them -- and picks the model as they do. That one approval covers up to
    10 images in this run, generated and edited together, so a few rounds of EditImage to
    refine the result go through without asking again. Put every image the request needs
    in one call (three banners are one call with three images), and never call it
    speculatively."""

    project: str = Field(description=PROJECT)
    images: list[ImageSpec] = Field(min_length=1, max_length=config.MAX_IMAGES_PER_CALL)
    model: Literal["gpt-image-2.5-flare", "gpt-image-2.5-sunburst"] = Field(
        default="gpt-image-2.5-flare", description=MODEL
    )


class EditImage(BaseModel):
    """Make a new image from up to four existing images in a project -- change part of a
    photo, restyle it, put a product into a scene, combine references -- and save it.

    Approval works as for GenerateImages: the run's first image call asks, and that
    approval covers up to 10 images in the run, edits included -- so refine over a few
    rounds when the result needs it, reading each one before the next. For the user's
    own variations, ask for them in one call through output_paths."""

    project: str = Field(description=PROJECT)
    source_paths: list[str] = Field(
        min_length=1,
        max_length=config.MAX_REFERENCE_IMAGES,
        description="The images to start from, in that project. The first is the one edited.",
    )
    prompt: str = Field(description="What to change or make, in detail, and what to keep exactly.")
    output_paths: list[str] = Field(
        min_length=1,
        max_length=config.MAX_IMAGES_PER_CALL,
        description="Where to save each result; one variation is made per path.",
    )
    mask_path: str | None = Field(
        default=None,
        description="Optional PNG with transparency over the area to change; the same size "
        "as the first source image.",
    )
    size: Size = Field(default="auto")
    quality: Quality = Field(default="auto")
    background: Background = Field(default="auto")
    model: Literal["gpt-image-2.5-flare", "gpt-image-2.5-sunburst"] = Field(
        default="gpt-image-2.5-flare", description=MODEL
    )

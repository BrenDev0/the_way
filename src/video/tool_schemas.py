from typing import Literal

from pydantic import BaseModel, Field

from src.media.tool_schemas import Position

PROJECT = (
    "Project to save the video in, exactly as ListProjects shows it. Source files are read "
    "from it too, unless written project:<name>/<path> for another of the user's projects"
)
PROMPT = (
    "Everything the clip must show, in detail: subject, action, camera movement, shot "
    "changes, lighting, style, mood, and any sound or dialogue wanted. NEVER ask for readable "
    "text, signs, captions, logos or labels in the picture: a video model cannot spell and draws "
    "gibberish. Describe blank surfaces instead (a plain panel, an empty wall, a blank screen) "
    "and end the prompt with 'no text, no letters, no logos'; the words are added afterwards "
    "with AddTextToVideo."
)
OUTPUT_PATH = "Where to save it inside the project, ending in .mp4 -- for example 'campana/teaser.mp4'."
SECONDS = (
    "Length in seconds. Seedance 2.0 and Kling 3.0 make 3-15, Seedance 2.5 and Kling 4.0 up "
    "to 30; longer costs more. Leave it out for the model's default."
)
MODEL = (
    "{options} The user picks the final model when they approve, so this is your suggestion."
)
SEEDANCE = "seedance-2.5 or seedance-2.0 (realism, several scenes in one clip)"
KLING_3 = "kling-3 (the cheapest, good for any shot without a talking person)"
KLING_4 = "kling-4 (the best quality for the price, the default)"
KLING_OMNI = "kling-omni (Kling O3: restyle or change a clip while keeping its motion)"

AspectRatio = Literal["16:9", "9:16", "1:1", "21:9", "4:3", "3:4"]


class GenerateVideo(BaseModel):
    """Generate a video clip from text on fal and save it in a project as an .mp4.

    It spends the user's money -- far more than an image -- so the user approves every
    call, even inside a background task, which waits for them, and picks the model as they
    do. One call makes one clip and can take several minutes. Write the full prompt first and
    never call it speculatively.

    Never present a generated clip as footage of a specific real person, venue or event."""

    project: str = Field(description=PROJECT)
    prompt: str = Field(description=PROMPT)
    output_path: str = Field(description=OUTPUT_PATH)
    seconds: int | None = Field(default=None, ge=3, le=30, description=SECONDS)
    aspect_ratio: AspectRatio = Field(
        default="16:9",
        description="16:9 landscape, 9:16 vertical (reels, stories, TikTok), 1:1 square. "
        "Kling 3.0 makes only those three.",
    )
    model: Literal["kling-4", "kling-3", "seedance-2.5", "seedance-2.0"] = Field(
        default="kling-4", description=MODEL.format(options=f"{KLING_4}, {KLING_3}, {SEEDANCE}.")
    )


class AnimateImage(BaseModel):
    """Make a video clip that starts from an image in a project -- a product shot, a
    photo, a generated image -- moving as the prompt says, and save it as an .mp4.

    Approval works as for GenerateVideo: every call asks, and the user picks the model.
    The image sets the framing, so make or crop it to the shape wanted first."""

    project: str = Field(description=PROJECT)
    image_path: str = Field(
        description="The image to start from, in that project or as project:<name>/<path>."
    )
    prompt: str = Field(description=PROMPT)
    output_path: str = Field(description=OUTPUT_PATH)
    end_image_path: str | None = Field(
        default=None,
        description="Optional image the clip should end on, for a transition between two frames.",
    )
    seconds: int | None = Field(default=None, ge=3, le=30, description=SECONDS)
    model: Literal["kling-4", "kling-3", "seedance-2.5", "seedance-2.0"] = Field(
        default="kling-4", description=MODEL.format(options=f"{KLING_4}, {KLING_3}, {SEEDANCE}.")
    )


class EditVideo(BaseModel):
    """Make a new video from an existing clip in a project -- restyle it, change the
    setting, swap or add an object or character, change the weather -- keeping its motion,
    and save it as an .mp4. The source must be 3 to 15 seconds for kling-omni, up to 30
    for kling-4.

    Approval works as for GenerateVideo: every call asks, and the user picks the model."""

    project: str = Field(description=PROJECT)
    video_path: str = Field(
        description="The clip to edit (.mp4 or .mov), in that project or as project:<name>/<path>."
    )
    prompt: str = Field(
        description="What to change and what to keep exactly. Refer to the source clip as "
        "@Video1 and to reference images as @Image1, @Image2 and so on."
    )
    output_path: str = Field(description=OUTPUT_PATH)
    reference_image_paths: list[str] = Field(
        default_factory=list,
        max_length=4,
        description="Optional images of a character, product or style to bring into the clip.",
    )
    model: Literal["kling-4", "kling-omni"] = Field(
        default="kling-4", description=MODEL.format(options=f"{KLING_4} or {KLING_OMNI}.")
    )


class TextCard(BaseModel):
    """One piece of text on the clip: the words, when they show, and where."""

    text: str = Field(min_length=1, max_length=400, description="The exact words, accents included; line breaks are kept")
    start_seconds: float = Field(default=0, ge=0, description="Seconds into the clip when it appears; 0 is the first frame")
    end_seconds: float | None = Field(
        default=None, gt=0, description="Seconds into the clip when it disappears. Leave it out to keep it to the end."
    )
    position: Position = Field(default="bottom")


class AddTextToVideo(BaseModel):
    """Put exact text on a video clip in a project -- a title, a caption, a price, a call to
    action, a name -- and save a new .mp4. This is the ONLY way to get readable text in a
    video: a model that generates video cannot spell, so make the clip with no text in it
    and add every word here. The words come out exactly as written, in a clean font, with
    accents. One call can put several pieces of text on one clip at different seconds (a
    title, then a caption, then a closing line); do it in one call, because each call
    re-encodes the clip. It costs nothing and the sound is kept as it is.

    For text on a still picture use AddTextToImage."""

    project: str = Field(description=PROJECT)
    video_path: str = Field(description="The clip (.mp4 or .mov), in that project or as project:<name>/<path>.")
    texts: list[TextCard] = Field(min_length=1, max_length=12, description="What to show, each with its own seconds and position")
    output_path: str | None = Field(
        default=None,
        description="Where to save it, ending in .mp4. Defaults to the clip's name with '-con-texto' added, beside it.",
    )
    size: int | None = Field(default=None, ge=6, le=1000, description="Letter height in pixels; about 1/18 of the width by default.")
    color: str = Field(default="white", description="Text colour: a name or a hex like '#ffcc00'")
    font: Literal["sans", "sans-bold", "serif"] = Field(default="sans-bold")
    box: str | None = Field(
        default=None,
        description="A colour for a box behind the text, e.g. 'black', so it reads over any footage. Recommended for captions.",
    )
    box_opacity: float = Field(default=0.6, ge=0, le=1)
    margin: int | None = Field(default=None, ge=0, description="Distance from the edge in pixels.")
    max_width: float = Field(default=0.9, ge=0.2, le=1, description="Widest the text may run, as a share of the video's width.")
    fade_seconds: float = Field(default=0.25, ge=0, le=2, description="Fade in and out of each text; 0 for a hard cut.")
    overwrite: bool = Field(default=False, description="Replace a file already at output_path. Only when the user asked for that.")

from typing import Literal

from pydantic import BaseModel, Field

PROJECT = (
    "Project to save the video in, exactly as ListProjects shows it. Source files are read "
    "from it too, unless written project:<name>/<path> for another of the user's projects"
)
PROMPT = (
    "Everything the clip must show, in detail: subject, action, camera movement, shot "
    "changes, lighting, style, mood, and any sound or dialogue wanted."
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
    do. One call makes one clip and takes a few minutes. Write the full prompt first and
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

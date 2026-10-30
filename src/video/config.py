from dataclasses import dataclass

# Every model runs on fal (fal.ai), on the organization's fal key. Each one names its fal
# endpoint per mode -- None where it does not do that -- and the inputs that endpoint takes,
# which differ between families: Kling wants start_image_url and Kling 4 an integer duration.


@dataclass(frozen=True)
class VideoModel:
    label: str
    text: str | None  # text to video
    image: str | None  # image to video
    edit: str | None  # video to video edit
    image_field: str = "image_url"
    min_seconds: int = 4
    max_seconds: int = 15
    seconds_as_int: bool = False
    # text to video only: from an image, the image sets the frame
    aspect_ratios: tuple[str, ...] = ()


SEEDANCE_25 = "seedance-2.5"
SEEDANCE_20 = "seedance-2.0"
KLING_3 = "kling-3"
KLING_4 = "kling-4"
KLING_OMNI = "kling-omni"

SEEDANCE_RATIOS = ("21:9", "16:9", "4:3", "1:1", "3:4", "9:16")

MODELS_BY_KEY = {
    SEEDANCE_25: VideoModel(
        label="Seedance 2.5",
        text="bytedance/seedance-2.5/text-to-video",
        image="bytedance/seedance-2.5/image-to-video",
        edit=None,
        max_seconds=30,
        aspect_ratios=SEEDANCE_RATIOS,
    ),
    SEEDANCE_20: VideoModel(
        label="Seedance 2.0",
        text="bytedance/seedance-2.0/text-to-video",
        image="bytedance/seedance-2.0/image-to-video",
        edit=None,
        aspect_ratios=SEEDANCE_RATIOS,
    ),
    KLING_3: VideoModel(
        label="Kling 3.0",
        text="fal-ai/kling-video/v3/pro/text-to-video",
        image="fal-ai/kling-video/v3/pro/image-to-video",
        edit=None,
        image_field="start_image_url",
        min_seconds=3,
        aspect_ratios=("16:9", "9:16", "1:1"),
    ),
    KLING_4: VideoModel(
        label="Kling 4.0",
        text="kling/v4/text-to-video",
        image="kling/v4/image-to-video",
        edit="kling/v4/video-to-video/edit",
        image_field="start_image_url",
        min_seconds=3,
        max_seconds=30,
        seconds_as_int=True,
        aspect_ratios=("16:9", "9:16", "1:1", "21:9"),
    ),
    KLING_OMNI: VideoModel(
        label="Kling Omni (O3)",
        text=None,
        image=None,
        edit="fal-ai/kling-video/o3/standard/video-to-video/edit",
    ),
}

# Whoever approves picks among the models that do what the call asks.
TEXT_MODELS = tuple(key for key, model in MODELS_BY_KEY.items() if model.text)
IMAGE_MODELS = tuple(key for key, model in MODELS_BY_KEY.items() if model.image)
EDIT_MODELS = tuple(key for key, model in MODELS_BY_KEY.items() if model.edit)
DEFAULT_MODEL = KLING_4

QUEUE_URL = "https://queue.fal.run"
UPLOAD_URL = "https://rest.fal.ai/storage/upload/initiate?storage_type=gcs"

# What the endpoints accept as sources: Kling 4 takes images up to 30 MB, and Kling Omni
# videos up to 200 MB.
MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_VIDEO_BYTES = 200 * 1024 * 1024

# A video is made as a job on fal's side: submitted, then polled until it is done. A long
# or high-resolution clip takes several minutes.
REQUEST_TIMEOUT_SECONDS = 120
POLL_SECONDS = 5
TIMEOUT_SECONDS = 900

# OpenAI's GPT Image 2.5 pair. Flare is the fast default -- GPT Image 2 quality at about
# half the latency. Sunburst is the most capable, with more detail and style, and keeps
# details best across repeated edits. Whoever approves the call picks between them.
FLARE = "gpt-image-2.5-flare"
SUNBURST = "gpt-image-2.5-sunburst"
MODELS = (FLARE, SUNBURST)
DEFAULT_MODEL = FLARE

SIZES = ("auto", "1024x1024", "1536x1024", "1024x1536")
QUALITIES = ("auto", "low", "medium", "high", "xhigh", "max")
BACKGROUNDS = ("auto", "opaque", "transparent")
FORMATS = ("png", "jpeg", "webp")

# One approval covers a run's images -- the first call asks, and the rest of that run (a
# chat reply, a background task) goes on without asking, up to this many images in all,
# generated and edited together, with the model the user picked. Past it, it asks again.
IMAGES_PER_APPROVAL = 10

MAX_IMAGES_PER_CALL = 8


def images_in(name: str, args: dict) -> int:
    """How many images a call makes -- what it costs against the run's allowance."""
    if name == "GenerateImages":
        return max(1, len(args.get("images") or []))
    if name == "EditImage":
        return max(1, len(args.get("output_paths") or []))
    return 0
# What the edit endpoint accepts as references.
MAX_REFERENCE_IMAGES = 4
MAX_REFERENCE_BYTES = 50 * 1024 * 1024

# A single image at max quality can take a while.
REQUEST_TIMEOUT_SECONDS = 300

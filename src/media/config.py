# What one call may read. A scanned PDF or a camera photo fits; a video does not.
MAX_INPUT_BYTES = 80 * 1024 * 1024
MAX_FILES_PER_CALL = 50

# Rendering PDF pages to images: one call, a sensible number of pages, a sensible size.
MAX_RENDER_PAGES = 60
DEFAULT_RENDER_DPI = 150
MAX_RENDER_DPI = 400

# Pillow refuses images past its own limit as a "decompression bomb"; this is that limit,
# set explicitly: a 200-megapixel image is a real photo, a billion pixels is an attack.
MAX_IMAGE_PIXELS = 200_000_000
MAX_OUTPUT_SIDE = 12_000

# Text read out of a PDF goes into the model's context.
MAX_TEXT_CHARS = 60_000

# Paper sizes for ImagesToPdf, in points (1/72 in).
PAGE_SIZES_PT = {"A4": (595.28, 841.89), "Letter": (612.0, 792.0)}

# Fonts the Docker image installs (Dockerfile); Pillow's own is the fallback.
FONTS = {
    "sans": ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    "sans-bold": ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    "serif": ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
}

IMAGE_FORMATS = {"png": "PNG", "jpeg": "JPEG", "jpg": "JPEG", "webp": "WEBP"}
CONTENT_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg", "webp": "image/webp", "pdf": "application/pdf"}

# OpenAI's limit on one audio file sent to be transcribed.
MAX_AUDIO_BYTES = 25 * 1024 * 1024
# Longer than this is refused before anything is downloaded: past it the audio would not
# fit in one transcription anyway, and the wait would outlast a turn.
MAX_SECONDS = 2 * 60 * 60

TRANSCRIBE_MODEL = "gpt-4o-transcribe"
# gpt-4o-transcribe refuses audio past its own length limit; whisper takes any length that
# fits in the file limit.
FALLBACK_MODEL = "whisper-1"
REQUEST_TIMEOUT_SECONDS = 600

# Where a transcript is kept, in the workspace (.the_way), so it is read again rather than
# fetched again.
FOLDER = "transcripts"

# Shown to the model in full up to here; the whole text is in the saved file.
MAX_RETURNED_CHARS = 40_000

# The platforms audio may be fetched from. A link anywhere else is refused: the server would
# otherwise fetch whatever address it was handed, internal ones included.
PLATFORM_HOSTS = (
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "instagram.com",
    "facebook.com",
    "fb.watch",
    "vimeo.com",
    "x.com",
    "twitter.com",
    "linkedin.com",
    "twitch.tv",
    "dailymotion.com",
    "soundcloud.com",
)
# yt-dlp's extractors for those platforms; its generic extractor, which fetches any page,
# is left out.
EXTRACTORS = (
    r"youtube.*",
    r"tiktok.*",
    r"instagram.*",
    r"facebook.*",
    r"vimeo.*",
    r"twitter.*",
    r"linkedin.*",
    r"twitch.*",
    r"dailymotion.*",
    r"soundcloud.*",
)

AUDIO_TYPES = ("audio/", "video/")
# by name too: an upload does not always say it is audio
AUDIO_SUFFIXES = (".mp3", ".m4a", ".wav", ".ogg", ".oga", ".opus", ".webm", ".mp4", ".mov", ".mpeg", ".mpga", ".flac", ".aac")

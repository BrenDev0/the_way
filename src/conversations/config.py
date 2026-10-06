MODEL = "gpt-5.4"
TEMPERATURE = 0.0
MAX_ITERATIONS = 40

# A conversation still called by its placeholder is named after its first exchange, by the
# cheapest model of whichever provider the user has a key for -- a few words need no more.
TITLE_MODELS = ("claude-haiku-4-5-20251001", "gpt-5.4-nano")
TITLE_TEMPERATURE = 0.0
# What the desktop app and the API name a conversation nobody named. Any other title was
# chosen, and is kept.
PLACEHOLDER_TITLES = ("Nueva conversación", "New conversation")
MAX_TITLE_CHARS = 60
# Enough of each side to tell what it is about; the rest only costs tokens.
TITLE_EXCERPT_CHARS = 1500

# Files attached to a message (attachments.py). They land in the drafts project, here.
ATTACHMENTS_FOLDER = "adjuntos"
MAX_ATTACHMENTS = 10
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
# Images are sent as pictures in this many of the latest messages that have attachments;
# further back the model is told where the file is instead. Each picture is re-sent on
# every turn, so this is what keeps a long conversation with images affordable.
ATTACHMENT_IMAGE_MESSAGES = 3
# Past this the models scale an image down themselves; sending it bigger only costs time.
ATTACHMENT_IMAGE_MAX_SIDE = 1568
ATTACHMENT_IMAGE_MAX_BYTES = 3 * 1024 * 1024
# How much of an attached PDF, Word or text file the model is given to read.
ATTACHMENT_TEXT_CHARS = 30_000
ATTACHMENT_CACHE_SIZE = 32

# How long an events stream may stay silent before a keep-alive goes out.
KEEP_ALIVE_SECONDS = 15

# An events stream ends after this long; the client reconnects with Last-Event-ID.
STREAM_MAX_SECONDS = 30 * 60

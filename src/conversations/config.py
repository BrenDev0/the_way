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

# How long an events stream may stay silent before a keep-alive goes out.
KEEP_ALIVE_SECONDS = 15

# An events stream ends after this long; the client reconnects with Last-Event-ID.
STREAM_MAX_SECONDS = 30 * 60

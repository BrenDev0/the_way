MODEL = "gpt-5.4"
TEMPERATURE = 0.0
MAX_ITERATIONS = 40

# How long an events stream may stay silent before a keep-alive goes out.
KEEP_ALIVE_SECONDS = 15

# An events stream ends after this long; the client reconnects with Last-Event-ID.
STREAM_MAX_SECONDS = 30 * 60

TRANSCRIBE_MODEL = "gpt-4o-transcribe"
SPEAK_MODEL = "gpt-4o-mini-tts"
SPEAK_VOICE = "cedar"

# Delivery rate. The default reads an answer noticeably slower than anyone says one out
# loud. 1.0 is the API default, 4.0 the ceiling; 1.2 takes about a fifth off, 1.5 starts
# to sound hurried. Asking for it through instructions instead barely registers.
SPEAK_SPEED = 1.2

# Raw 16-bit mono pcm at this rate is what the speech endpoint streams back.
PLAYBACK_RATE = 24000

# A quarter second of audio per chunk: small enough that playback starts promptly, large
# enough that the next chunk is there before the speakers run dry.
CHUNK_BYTES = PLAYBACK_RATE // 2

MAX_SPEAK_CHARS = 4000

# Two minutes of 16 kHz 16-bit mono wav is about 3.8 MB -- the client caps a recording
# there. Anything much bigger is not a turn someone spoke.
MAX_AUDIO_BYTES = 5 * 1024 * 1024

# Under a quarter second of audio is a mistaken press, not speech.
MIN_AUDIO_BYTES = 8000

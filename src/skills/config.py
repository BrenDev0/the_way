NAME_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
MAX_NAME_CHARS = 64
MAX_DESCRIPTION_CHARS = 500
MAX_INSTRUCTIONS_CHARS = 100_000
MAX_SKILLS_PER_ORGANIZATION = 200

# Example requests that should route to a skill. They are listed beside its description in
# the agent's skill index, so they cost context in every conversation: keep them few.
MAX_TRIGGERS = 10
MAX_TRIGGER_CHARS = 200

# Reference files a skill points to by relative path (a brief, a list of laws, a
# stylesheet). Text only; read on demand, never listed whole in the context.
FILE_PATH_PATTERN = r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$"
MAX_FILE_PATH_CHARS = 255
MAX_FILES_PER_SKILL = 30
MAX_FILE_CHARS = 100_000
MAX_FILES_TOTAL_CHARS = 400_000

# One import carries a whole kit; the organization limit still applies on top.
MAX_SKILLS_PER_IMPORT = 50

MAX_NAME_CHARS = 255

# Anything Windows cannot put on disk, so every tree can sync to the desktop app.
INVALID_NAME_CHARS = frozenset('<>:"/\\|?*')
RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)

# S3 refuses a single PUT above 5 GB, so a presigned upload cannot go past it.
MAX_FILE_BYTES = 5 * 1024 * 1024 * 1024

UPLOAD_URL_TTL_SECONDS = 60 * 15

# What GET .../content will send through the server in one response, to be opened or
# saved by the desktop app. A bigger file is still reachable by its presigned URL.
MAX_CONTENT_BYTES = 200 * 1024 * 1024
DOWNLOAD_URL_TTL_SECONDS = 60 * 5

# Each user's own workspace, created the first time something needs it: background task
# output, fetched CX datasets and the brand override live here, the way they lived under
# ~/.the_way/ in the command-line assistant.
WORKSPACE_PROJECT = ".the_way"

# Where finished work lands when the user has not said where they want it, so the agent
# does not have to ask before every task. A project of its own, browsable like any other,
# created the first time something is delivered to it.
DRAFTS_PROJECT = "Borradores"

# Created on first use rather than refused as unknown.
AUTO_CREATED_PROJECTS = {WORKSPACE_PROJECT.lower(): WORKSPACE_PROJECT, DRAFTS_PROJECT.lower(): DRAFTS_PROJECT}

# What the agent's tools will read or write in one call. A file above this is refused
# rather than truncated, because a truncated edit writes back a damaged file.
MAX_TOOL_FILE_BYTES = 2 * 1024 * 1024
MAX_TOOL_READ_CHARS = 60_000
MAX_SEARCH_RESULTS = 50

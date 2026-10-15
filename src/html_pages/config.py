# Design quality tracks model quality here more sharply than in any other assistant -- the
# difference is visible in the output. The first model whose provider the user holds a key
# for is used, so a missing Anthropic key degrades the page instead of failing the tool.
MODELS = ("claude-sonnet-5", "gpt-5.4")

# High for the director (design choices should vary between pages, not converge on one
# safe look), low for the builder (it is executing a decision, not making one).
DESIGNER_TEMPERATURE = 0.9
BUILDER_TEMPERATURE = 0.3

DESIGNER_MAX_ITERATIONS = 4

# A page, a real revision pass, and room for web lookups when the brief needs content.
BUILDER_MAX_ITERATIONS = 25

DESIGNER_TOOLS = frozenset({"ReadProjectFile", "FindProjectFiles"})

# The builder writes one page. It must not spawn workers, author skills, recurse into
# itself, or remove anything -- a page builder has no business deleting files.
BUILDER_TOOLS = frozenset(
    {
        "ReadProjectFile",
        "FindProjectFiles",
        "ListProjectFolder",
        "CreateProjectFolder",
        "WriteProjectFile",
        "EditProjectFile",
        "CheckPage",
        "WebSearch",
        "ExtractWebPages",
        "MapWebPages",
    }
)

# A brand pack's identity.md and voice.md go to both passes whole; past this they are cut.
MAX_BRAND_FILE_CHARS = 8_000

# A skill named for the page goes to both passes: its text, then its reference files, until
# this budget is spent (the kit's largest, output-documents, is about 47 000 without its
# script). Files past it are named, not sent.
MAX_SKILL_CHARS = 60_000

# Reference files that are programs, not method: the builder cannot run them, and a page
# carries no runtime script.
SKILL_FILES_LEFT_OUT = (".js", ".mjs", ".py", ".sh")

# CheckPage hands the builder screenshots of its page: the top of it at desktop and phone
# width, two per check. A page gets this many in all -- two check rounds, as the prompt asks.
MAX_SCREENSHOTS_PER_PAGE = 4
DESKTOP_WIDTH = 1440
PHONE_WIDTH = 375
# how much of the page, from the top, each shows (two screens' worth)
DESKTOP_KEEP_HEIGHT = 1800
PHONE_KEEP_HEIGHT = 1624
# the long side models read at without scaling an image down themselves
SCREENSHOT_MAX_SIDE = 1568

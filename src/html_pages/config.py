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
        "WebSearch",
        "ExtractWebPages",
        "MapWebPages",
    }
)

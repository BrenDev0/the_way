# The strongest model the user holds a key for, deliberately above the conversation
# assistant. This is the only agent that runs with nobody watching, it runs the deepest
# loop, and it writes the artifact the client actually opens -- model quality is the only
# guardrail on that path.
MODELS = ("claude-opus-5", "gpt-5.4")
TEMPERATURE = 0.5

# One step is one model reply, not one tool call. Headroom for work that is genuinely long
# rather than merely inefficient; the prompt handles the inefficient kind.
MAX_ITERATIONS = 80

TASKS_FOLDER = "tasks"

# What a worker may use. No desktop tools (nobody is at the desktop), nothing destructive
# (it writes into its own task folder; delivery is the runtime's job), no background tools
# (workers must not spawn workers), and no preferences or history (a worker cannot ask,
# so it must not guess intent from old sessions or write standing rules nobody agreed to).
TOOLS = frozenset(
    {
        "ReadKnowledgeDocument",
        "ReadSkill",
        "ListProjects",
        "ListProjectFolder",
        "FindProjectFiles",
        "ReadProjectFile",
        "WriteProjectFile",
        "EditProjectFile",
        "CreateProjectFolder",
        "BuildHtmlPage",
        "HtmlToPdf",
        "HtmlToPng",
        # exact PDF and image edits: they only ever write new files
        "ReadPdf",
        "EditPdfPages",
        "MergePdfs",
        "PdfToImages",
        "ImagesToPdf",
        "InspectImage",
        "TransformImage",
        "AddTextToImage",
        "OverlayImage",
        # Always ask: the worker suspends on these until the user approves (see jobs.py).
        "GenerateImages",
        "EditImage",
        "WebSearch",
        "MapWebPages",
        "ExtractWebPages",
        "CrawlWebPages",
        "WebResearch",
        "SearchCXOperations",
        "DescribeCXOperation",
        "ExecuteCXOperation",
        "FetchCXDataset",
        "QueryCXDataset",
    }
)

MCP_URL = "https://services.leadconnectorhq.com/mcp/v2"
MCP_TIMEOUT_SECONDS = 60

# A hard stop on the page loop itself, independent of max_rows. A strategy whose cursor
# works but never advances would otherwise page forever against the user's live API.
MAX_PAGES = 600

# GHL's documented burst allowance is 100 requests per 10 seconds per location. At 100
# rows a page that is 10,000 rows of headroom per 10 seconds, so pacing costs nothing
# real and keeps a large fetch from tripping a 429 halfway through.
PAGE_PAUSE_SECONDS = 0.15

# Datasets live in the user's workspace project, one folder per pull.
DATA_FOLDER = "data"
ROWS_FILE = "rows.ndjson"
MANIFEST_FILE = "manifest.json"

MAX_QUERY_GROUPS = 200

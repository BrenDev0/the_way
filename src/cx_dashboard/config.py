API_URL = "https://services.leadconnectorhq.com"
API_VERSION = "2021-07-28"
TIMEOUT_SECONDS = 30

# GHL allows 100 requests per 10 seconds per location; a dashboard makes a few dozen, so a
# handful at once with a short pause between pages never comes near it.
CONCURRENCY = 4
PAGE_PAUSE_SECONDS = 0.1
# Told to slow down, wait this long (or what Retry-After says) and try again, this often.
RETRY_AFTER_SECONDS = 2.0
RETRIES = 2
PAGE_SIZE = 100

# Caps on what one dashboard reads. Past them a section says it is partial rather than
# paging the account for minutes.
MAX_CONTACTS = 3_000
MAX_OPPORTUNITIES = 5_000
MAX_WAITING_CONVERSATIONS = 1_000
MAX_TRANSACTIONS = 2_000
MAX_SUBSCRIPTIONS = 1_000
MAX_SUBMISSIONS = 2_000
MAX_POSTS = 500
MAX_TASKS = 1_000
# An ad's detail lists this many of its leads, newest first.
MAX_AD_LEADS = 200
# A conversation opens on its latest messages; older ones load on request.
CONVERSATION_PAGE = 40
MAX_REPLY_CHARS = 1_600
# Contact tags that mark a chat handed from the AI agent to a person, in the words agencies use.
HANDOVER_TAGS = ("human handover", "transferencia a humano", "handover", "humano", "stop bot")
# First-response time reads each conversation's messages, one request apiece: a sample
# of the most recent is enough for a median and keeps the dashboard to a few seconds.
RESPONSE_SAMPLE = 40
MESSAGES_PER_CONVERSATION = 40
# Growth looks back this many calendar months: the current one, the last full one, and
# twelve before it -- so the last full month has the same month a year earlier to compare.
GROWTH_MONTHS = 14

PERIODS = (7, 30, 90)
DEFAULT_PERIOD = 30
DEFAULT_TIMEZONE = "America/Mexico_City"

# An open deal whose stage has not moved in this long needs someone to look at it.
STALE_DAYS = 14
UPCOMING_DAYS = 7
TOP = 8

CACHE_SECONDS = 10 * 60

# The scope each part of the dashboard needs, named as GHL names it in the private
# integration's settings -- what the user adds when a section says it is locked.
SCOPES = {
    "leads": "contacts.readonly",
    "inbox": "conversations.readonly",
    "pipeline": "opportunities.readonly",
    "appointments": "calendars.readonly + calendars/events.readonly",
    "team": "users.readonly",
    "payments": "payments/transactions.readonly",
    "retention": "payments/transactions.readonly",
    "subscriptions": "payments/subscriptions.readonly",
    "nps": "surveys.readonly",
    "social": "socialplanner/account.readonly + socialplanner/statistics.readonly",
    "growth": "contacts.readonly + opportunities.readonly",
    "conversion": "contacts.readonly + opportunities.readonly",
    "response": "conversations.readonly + conversations/message.readonly",
    "ads": "contacts.readonly",
    "tasks": "locations/tasks.readonly",
    "handovers": "contacts.readonly",
    "account": "locations.readonly",
}

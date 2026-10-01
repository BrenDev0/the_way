TAVILY_URL = "https://api.tavily.com"

# Search and extract answer in seconds; a crawl can take minutes.
TIMEOUT_SECONDS = 60
CRAWL_TIMEOUT_SECONDS = 300

# Research runs as a job on Tavily's side: started, then polled until it is done. A deep
# ("pro") run takes several minutes.
RESEARCH_POLL_SECONDS = 5
RESEARCH_TIMEOUT_SECONDS = 900

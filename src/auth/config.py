# Where each client reaches the API. The prefix decides how a request is authenticated:
# the front end's routes take a session cookie and its request signature, the desktop
# app's take a bearer token and nothing else. Neither accepts the other's credential.
WEB_API_PREFIX = "/api/v1"
DESKTOP_API_PREFIX = "/api/desktop/v1"

BEARER_SCHEME = "bearer"

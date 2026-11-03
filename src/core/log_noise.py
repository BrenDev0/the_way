"""Libraries that log every request they make, which buries what matters.

The HTTP clients under the model and video providers log one INFO line per request, and a video
job is polled every few seconds for minutes: the worker's log was almost all "HTTP Request: GET
.../status 202 Accepted". Warnings and errors still come through; only the per-request
chatter is turned down.
"""

import logging

# httpx2 is the name a bundled copy of the client logs under, beside httpx itself
NOISY_LOGGERS = ("httpx", "httpx2", "httpcore")


def quiet_http_clients() -> None:
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

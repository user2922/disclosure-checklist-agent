"""Named failures. Each maps to exactly one HTTP status in app/main.py.

Generic messages only — standing Rule 5. Detail goes to the server log and the
audit trail, never to the client.
"""


class DisclosureAgentError(Exception):
    """Base class, so a route can catch everything this app raises deliberately."""


class RateLimitExceeded(DisclosureAgentError):
    """Too many requests from one caller. 429."""


class DailyCeilingExceeded(DisclosureAgentError):
    """The process-wide daily model-call ceiling is spent. 429."""


class ModelUnavailable(DisclosureAgentError):
    """The configured model could not be reached or does not exist. 503."""


class ModelOutputError(DisclosureAgentError):
    """The model's output failed validation twice. 503.

    Never downgrade this to a partial checklist. A checklist missing an
    obligation is worse than no checklist.
    """

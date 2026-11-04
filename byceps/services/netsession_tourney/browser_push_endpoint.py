"""
byceps.services.netsession_tourney.browser_push_endpoint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Validate browser push subscriptions before storing them. The server later
sends HTTP requests to the endpoint, so only HTTPS URLs of the known push
services are accepted (otherwise anyone could make the server call arbitrary,
including internal, addresses).
"""

from __future__ import annotations

from urllib.parse import urlsplit


MAX_ENDPOINT_LENGTH = 2048

# Host names (or suffixes, starting with a dot) of the browsers' push services.
ALLOWED_PUSH_HOSTS = (
    'fcm.googleapis.com',  # Chrome, Edge (Chromium), Opera, Brave
    'android.googleapis.com',
    'updates.push.services.mozilla.com',  # Firefox
    'web.push.apple.com',  # Safari
    '.notify.windows.com',  # legacy Edge
)


def validate_push_subscription(
    endpoint: str, p256dh: str, auth: str
) -> str | None:
    """Return an error message, or `None` if the subscription is acceptable."""
    if not endpoint or not p256dh or not auth:
        return 'Subscription data is incomplete.'

    if not is_allowed_push_endpoint(endpoint):
        return 'Unsupported push service endpoint.'

    return None


def is_allowed_push_endpoint(endpoint: str) -> bool:
    if len(endpoint) > MAX_ENDPOINT_LENGTH:
        return False

    try:
        url = urlsplit(endpoint)
        port = url.port
    except ValueError:
        return False

    host = (url.hostname or '').lower()
    if url.scheme != 'https' or port not in (None, 443) or not host:
        return False

    return any(
        host.endswith(allowed) if allowed.startswith('.') else host == allowed
        for allowed in ALLOWED_PUSH_HOSTS
    )

"""
byceps.services.netsession_tourney.sponsor_link
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Normalize the target URL of a sponsor logo (rendered as `href`).
"""

from __future__ import annotations

from urllib.parse import urlsplit


MAX_LENGTH = 500


def normalize_target_url(target_url: str | None) -> str | None:
    """Return a safe http(s) URL or `None`.

    `example.org` becomes `https://example.org`; other schemes such as
    `javascript:` are dropped.
    """
    if target_url is None:
        return None

    normalized = target_url.strip()
    if not normalized:
        return None

    if '://' not in normalized and ':' not in normalized.split('/', 1)[0]:
        normalized = f'https://{normalized}'

    if urlsplit(normalized).scheme.lower() not in {'http', 'https'}:
        return None

    return normalized[:MAX_LENGTH]

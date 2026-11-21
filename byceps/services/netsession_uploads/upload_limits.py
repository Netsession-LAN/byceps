"""
byceps.services.netsession_uploads.upload_limits
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The upload size limit as users see it. The limit itself is the app's
`MAX_CONTENT_LENGTH`; nginx allows a bit more so that the app can answer
with a readable message.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from flask import current_app, request
from flask_babel import gettext


def get_max_upload_bytes() -> int:
    return int(current_app.config.get('MAX_CONTENT_LENGTH') or 0)


def format_megabytes(size_in_bytes: int) -> str:
    megabytes = size_in_bytes / (1024 * 1024)
    if megabytes == int(megabytes):
        return f'{int(megabytes)} MB'
    return f'{megabytes:.1f} MB'.replace('.', ',')


def build_too_large_message() -> str:
    return gettext(
        'Die Datei ist zu groß. Erlaubt sind höchstens %(limit)s.',
        limit=format_megabytes(get_max_upload_bytes()),
    )


def find_same_host_referrer_path() -> str | None:
    """The page the upload came from, if it is on this host (no open
    redirect)."""
    referrer = request.referrer
    if not referrer:
        return None
    parts = urlsplit(referrer)
    if parts.netloc != request.host:
        return None
    path = parts.path or '/'
    return f'{path}?{parts.query}' if parts.query else path

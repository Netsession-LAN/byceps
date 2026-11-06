"""
byceps.util.origin_check
~~~~~~~~~~~~~~~~~~~~~~~~

Netsession: CSRF protection for the site and admin apps.

BYCEPS forms carry no CSRF token; only `SameSite=Lax` session cookies
protect them. On top of that, writing requests (POST, PUT, PATCH, DELETE)
whose `Origin` (or, without it, `Referer`) points to another host are
refused. Requests with neither header pass, e.g. server-to-server
callbacks of payment providers.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from flask import abort, Flask, request
import structlog


log = structlog.get_logger()

_WRITING_METHODS = frozenset(['POST', 'PUT', 'PATCH', 'DELETE'])


def register(app: Flask) -> None:
    app.before_request(_refuse_foreign_writing_request)


def _refuse_foreign_writing_request() -> None:
    if request.method not in _WRITING_METHODS:
        return

    source = request.headers.get('Origin') or request.headers.get('Referer')
    if source is None:
        return

    source_host = urlsplit(source).hostname if source != 'null' else None
    own_host = urlsplit(f'//{request.host}').hostname
    if source_host is not None and source_host == own_host:
        return

    log.warning(
        'origin_check_refused',
        path=request.path,
        source=source[:200],
        host=request.host,
    )
    abort(403)

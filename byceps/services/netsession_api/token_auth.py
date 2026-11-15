"""
byceps.services.netsession_api.token_auth
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Token check for the read-only Netsession API (Screens and other clients).
Upstream's `api_token_required` does not look at token permissions, so
this one also requires `ns_api.read`: 401 without a valid token, 403
without the permission.
"""

from __future__ import annotations

from functools import wraps

from flask import abort, request
from werkzeug.datastructures import WWWAuthenticate

from byceps.services.authn.api import authn_api_service
from byceps.services.authz.models import PermissionID


READ_PERMISSION = PermissionID('ns_api.read')


def read_token_required(func):
    """401 without a valid token, 403 without `ns_api.read`."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        authorization = request.authorization
        token = (
            authorization.token
            if authorization is not None and authorization.type == 'bearer'
            else None
        )
        api_token = (
            authn_api_service.find_api_token_by_token(token) if token else None
        )
        if api_token is None or api_token.suspended:
            abort(401, www_authenticate=WWWAuthenticate('Bearer'))
        if READ_PERMISSION not in api_token.permissions:
            abort(403)
        return func(*args, **kwargs)

    return wrapper

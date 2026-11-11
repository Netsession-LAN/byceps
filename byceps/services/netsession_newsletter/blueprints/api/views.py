"""
byceps.services.netsession_newsletter.blueprints.api.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

API for the newsletter sync. `api_token_required` does not check token
permissions, so the views require `ns_newsletter.sync` themselves.
"""

from __future__ import annotations

from datetime import datetime, UTC
from functools import wraps
from uuid import UUID

from flask import abort, request
from werkzeug.datastructures import WWWAuthenticate

from byceps.services.authn.api import authn_api_service
from byceps.services.authz.models import PermissionID
from byceps.services.newsletter import newsletter_service
from byceps.services.user import user_service
from byceps.services.user.models import UserID
from byceps.util.framework.blueprint import create_blueprint
from byceps.util.views import jsonified

from ... import subscriber_queries, unsubscribe_service, unsubscribe_token
from ...settings import find_current_party_id


blueprint = create_blueprint('netsession_newsletter_api', __name__)

SYNC_PERMISSION = PermissionID('ns_newsletter.sync')


def sync_token_required(func):
    """401 without a valid token, 403 without the sync permission."""

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
        if SYNC_PERMISSION not in api_token.permissions:
            abort(403)
        return func(*args, **kwargs)

    return wrapper


@blueprint.get('/lists/<list_id>/subscribers')
@sync_token_required
@jsonified
def subscribers(list_id):
    list_ = _get_list_or_404(list_id)
    user_id = _parse_user_id(request.args.get('user_id'))
    rows = subscriber_queries.get_subscribers(
        list_.id, find_current_party_id(), user_id=user_id
    )
    return {
        'list_id': list_.id,
        'generated_at': _iso(datetime.utcnow()),
        'subscribers': [
            {
                'user_id': str(row.user_id),
                'screen_name': row.screen_name,
                'email_address': row.email_address,
                'first_name': row.first_name,
                'last_name': row.last_name,
                'is_orga_member': row.is_orga_member,
                'unsubscribe_token': unsubscribe_token.create(
                    row.user_id, list_.id
                ),
                'subscribed_at': _iso(row.subscribed_at),
            }
            for row in rows
        ],
    }


@blueprint.post('/lists/<list_id>/unsubscribe')
@sync_token_required
@jsonified
def unsubscribe(list_id):
    list_ = _get_list_or_404(list_id)
    data = request.get_json(silent=True) or {}
    user = _find_user(data)
    expressed_at = _parse_datetime(data.get('expressed_at'))
    outcome = unsubscribe_service.unsubscribe(user, list_, expressed_at)
    return {'status': outcome.value}


def _get_list_or_404(list_id):
    list_ = newsletter_service.find_list(list_id)
    if list_ is None:
        abort(404)
    return list_


def _parse_user_id(value: str | None) -> UserID | None:
    if not value:
        return None
    try:
        return UserID(UUID(value))
    except ValueError:
        abort(400, 'Invalid user_id.')


def _find_user(data: dict):
    user_id = _parse_user_id(data.get('user_id'))
    if user_id is not None:
        user = user_service.find_user(user_id)
    elif data.get('email_address'):
        user = user_service.find_user_by_email_address(data['email_address'])
    else:
        abort(400, 'user_id or email_address required.')
    if user is None:
        abort(404)
    return user


def _parse_datetime(value: str | None) -> datetime | None:
    """ISO 8601 (with Z or offset) to naive UTC; None if missing."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        abort(400, 'Invalid expressed_at.')
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _iso(value: datetime | None) -> str | None:
    return value.replace(microsecond=0).isoformat() + 'Z' if value else None

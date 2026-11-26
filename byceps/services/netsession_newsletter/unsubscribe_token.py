"""
byceps.services.netsession_newsletter.unsubscribe_token
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Signed token for the unsubscribe link in the newsletter mail. It only
allows unsubscribing, so it does not expire (old mails keep working).
Changing SECRET_KEY invalidates all links; the page then points to the
account settings.
"""

from __future__ import annotations

from uuid import UUID

from flask import current_app
from itsdangerous import BadSignature, URLSafeSerializer

from byceps.services.newsletter.models import ListID
from byceps.services.user.models import UserID


_SALT = 'ns-newsletter-unsubscribe'


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(current_app.config['SECRET_KEY'], salt=_SALT)


def create(user_id: UserID, list_id: ListID) -> str:
    return _serializer().dumps({'u': str(user_id), 'l': list_id})


def parse(token: str) -> tuple[UserID, ListID] | None:
    """Return user and list ID, or None for an invalid token."""
    try:
        data = _serializer().loads(token)
        return UserID(UUID(data['u'])), ListID(data['l'])
    except BadSignature, KeyError, TypeError, ValueError:
        return None

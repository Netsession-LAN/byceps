"""
byceps.services.netsession_newsletter.unsubscribe_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Unsubscribe a user on their behalf (mail link, or Sendy via the sync).
The subscription log records the user as initiator, like a click in the
account settings, and the usual signal tells the sync.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from byceps.services.newsletter import (
    newsletter_command_service,
    newsletter_service,
    signals as newsletter_signals,
)
from byceps.services.newsletter.models import List
from byceps.services.user.models import User


class UnsubscribeOutcome(Enum):
    unsubscribed = 'unsubscribed'
    already_unsubscribed = 'already_unsubscribed'


def unsubscribe(
    user: User, list_: List, expressed_at: datetime | None = None
) -> UnsubscribeOutcome:
    """Idempotent: an unsubscribed user stays as is."""
    if not newsletter_service.is_user_subscribed_to_list(user.id, list_.id):
        return UnsubscribeOutcome.already_unsubscribed

    _, event = newsletter_command_service.unsubscribe_user_from_list(
        user, list_, expressed_at or datetime.utcnow(), user
    ).unwrap()
    newsletter_signals.newsletter_unsubscribed.send(None, event=event)
    return UnsubscribeOutcome.unsubscribed

"""
byceps.services.netsession_newsletter.sync_webhook
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tells the newsletter sync about changes: newsletter (un)subscriptions,
account changes and orga team memberships (the orga flag drives the
Sendy segments). Posts JSON per RQ job with retry; the signature is
`sha256=HMAC(secret, timestamp + "." + body)`, made at delivery time so
retries carry a fresh timestamp.

Orga team memberships have no upstream signal, so a database hook on
`DbMembership` collects the users and reports them after the commit.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import hmac
import json
import time
from uuid import uuid4

import httpx
from rq import Retry
from sqlalchemy import event as sa_event, select
from sqlalchemy.orm import Session

from byceps.services.newsletter import signals as newsletter_signals
from byceps.services.orga_team.dbmodels import DbMembership
from byceps.services.user import signals as user_signals
from byceps.util.jobqueue import enqueue

from .settings import get_sync_secret, get_sync_url


_USER_SIGNAL_EVENTS = [
    (user_signals.screen_name_changed, 'user-updated'),
    (user_signals.email_address_changed, 'user-updated'),
    (user_signals.email_address_confirmed, 'user-updated'),
    (user_signals.details_updated, 'user-updated'),
    (user_signals.account_unsuspended, 'user-updated'),
    (user_signals.account_suspended, 'user-deactivated'),
    (user_signals.email_address_invalidated, 'user-deactivated'),
    (user_signals.account_deleted, 'user-deleted'),
]
_PENDING_KEY = 'ns_newsletter_orga_user_ids'
_connected = False


def send_event(
    event_name: str, user_id, list_id: str | None, occurred_at: datetime
) -> None:
    """Queue the event for the sync; does nothing without a sync URL."""
    url = get_sync_url()
    if url is None:
        return
    body = json.dumps(
        {
            'event': event_name,
            'event_id': str(uuid4()),
            'user_id': str(user_id),
            'list_id': list_id,
            'occurred_at': occurred_at.replace(microsecond=0).isoformat() + 'Z',
        }
    )
    enqueue(
        deliver,
        url,
        get_sync_secret(),
        body,
        retry=Retry(max=5, interval=[10, 60, 300, 900, 3600]),
    )


def deliver(url: str, secret: str, body: str) -> None:
    """RQ job: post the signed event; an error makes RQ retry."""
    timestamp = str(int(time.time()))
    content = body.encode()
    signature = hmac.new(
        secret.encode(), timestamp.encode() + b'.' + content, hashlib.sha256
    ).hexdigest()
    response = httpx.post(
        url,
        content=content,
        headers={
            'Content-Type': 'application/json',
            'X-NS-Timestamp': timestamp,
            'X-NS-Signature': f'sha256={signature}',
        },
        timeout=10,
    )
    response.raise_for_status()


def connect_signals() -> None:
    """Hook into the newsletter, user and orga team changes (once)."""
    global _connected
    if _connected:
        return
    _connected = True

    for signal, name in (
        (newsletter_signals.newsletter_subscribed, 'newsletter-subscribed'),
        (newsletter_signals.newsletter_unsubscribed, 'newsletter-unsubscribed'),
    ):
        signal.connect(_newsletter_receiver(name), weak=False)
    for signal, name in _USER_SIGNAL_EVENTS:
        signal.connect(_user_receiver(name), weak=False)

    sa_event.listen(DbMembership, 'after_insert', _remember_membership)
    sa_event.listen(DbMembership, 'after_update', _remember_membership)
    sa_event.listen(DbMembership, 'after_delete', _remember_membership)
    sa_event.listen(Session, 'do_orm_execute', _remember_bulk_delete)
    sa_event.listen(Session, 'after_commit', _report_memberships)
    sa_event.listen(Session, 'after_rollback', _forget_memberships)


def _newsletter_receiver(event_name: str):
    def receive(sender, *, event=None, **kwargs) -> None:
        send_event(event_name, event.user.id, event.list_id, event.occurred_at)

    return receive


def _user_receiver(event_name: str):
    def receive(sender, *, event=None, **kwargs) -> None:
        send_event(event_name, event.user.id, None, event.occurred_at)

    return receive


def _pending(session: Session) -> set:
    return session.info.setdefault(_PENDING_KEY, set())


def _remember_membership(mapper, connection, target: DbMembership) -> None:
    session = Session.object_session(target)
    if session is not None:
        _pending(session).add(target.user_id)


def _remember_bulk_delete(state) -> None:
    """`delete(DbMembership)` statements bypass the mapper hooks."""
    if not state.is_delete or state.bind_mapper is None:
        return
    if state.bind_mapper.class_ is not DbMembership:
        return
    where = state.statement.whereclause
    query = select(DbMembership.user_id)
    if where is not None:
        query = query.where(where)
    user_ids = state.session.execute(query).scalars().all()
    _pending(state.session).update(user_ids)


def _report_memberships(session: Session) -> None:
    user_ids = session.info.pop(_PENDING_KEY, set())
    now = datetime.utcnow()
    for user_id in user_ids:
        send_event('user-updated', user_id, None, now)


def _forget_memberships(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)

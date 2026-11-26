"""
byceps.services.netsession_tourney.browser_push_outbox
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Browser push delivery: processing the outbox, message payloads, retries.
"""

from __future__ import annotations

from base64 import urlsafe_b64encode
from datetime import datetime
import json

from cryptography.hazmat.primitives import serialization
from flask import current_app
import httpx
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError


try:
    from pywebpush import webpush, WebPushException
except ImportError:  # pragma: no cover - optional dependency during rollout
    WebPushException = Exception
    webpush = None
from byceps.database import db
from byceps.services.party.models import PartyID

from .browser_push_outbox_message import (
    build_browser_push_message_payload,
)
from .browser_push_outbox_rows import (
    _get_browser_push_private_key_pem,
    _get_browser_push_row_notification,
    _mark_browser_push_outbox_dead_letter,
    _mark_browser_push_sent,
    _schedule_browser_push_outbox_retry,
)
from .browser_push_service import (
    is_missing_browser_push_table_error,
)
from .dbmodels import (
    DbNetsessionTourneyBrowserPushOutbox,
    DbNetsessionTourneyBrowserPushSubscription,
    DbNetsessionTourneyNotification,
    DbNetsessionTourneyTournament,
)
from .models import BrowserPushOutboxStatus
from .notification_urls import find_browser_push_site_server_name
from .outbox_processing import process_outbox_rows


def process_browser_push_outbox(*, limit: int = 50) -> int:
    now = datetime.utcnow()
    try:
        db_rows = _load_due_browser_push_rows(now, limit)
    except DBAPIError as exc:
        if is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return 0
        raise

    process_outbox_rows(
        db_rows,
        _deliver_browser_push_row,
        _mark_browser_push_outbox_dead_letter,
        now,
        outbox_name='browser_push',
    )
    db.session.commit()
    return len(db_rows)


def _load_due_browser_push_rows(now: datetime, limit: int):
    return db.session.scalars(
        select(DbNetsessionTourneyBrowserPushOutbox)
        .filter(
            DbNetsessionTourneyBrowserPushOutbox.status.in_(
                [
                    BrowserPushOutboxStatus.pending.value,
                    BrowserPushOutboxStatus.failed.value,
                ]
            )
        )
        .filter(
            (DbNetsessionTourneyBrowserPushOutbox.next_attempt_at.is_(None))
            | (DbNetsessionTourneyBrowserPushOutbox.next_attempt_at <= now)
        )
        .order_by(DbNetsessionTourneyBrowserPushOutbox.created_at.asc())
        .limit(limit)
    ).all()


def _deliver_browser_push_row(db_row, now: datetime) -> None:
    """Push one notification to all browsers of its user, or schedule a
    retry, or give up. Nothing to send (push off, no subscription) counts
    as sent."""
    db_notification_and_tournament = _get_browser_push_row_notification(
        db_row, now
    )
    if db_notification_and_tournament is None:
        return

    db_notification, db_tournament = db_notification_and_tournament

    private_key_pem = _get_browser_push_private_key_pem(
        db_row, db_tournament, now
    )
    if private_key_pem is None:
        return

    db_subscriptions = _get_enabled_browser_push_subscriptions(
        db_tournament, db_notification
    )
    if not db_subscriptions:
        _mark_browser_push_sent(db_row)
        return

    delivered, transient_error = _push_to_subscriptions(
        db_subscriptions,
        db_tournament,
        message=build_browser_push_message_payload(
            db_tournament, db_notification
        ),
        vapid_private_key=_build_browser_push_private_key_for_pywebpush(
            private_key_pem
        ),
        now=now,
    )
    if delivered or transient_error is None:
        _mark_browser_push_sent(db_row)
        return

    _schedule_browser_push_outbox_retry(
        db_row, f'Browser push delivery failed: {transient_error}', now
    )


def _get_enabled_browser_push_subscriptions(
    db_tournament: DbNetsessionTourneyTournament,
    db_notification: DbNetsessionTourneyNotification,
):
    return db.session.scalars(
        select(DbNetsessionTourneyBrowserPushSubscription).filter_by(
            party_id=db_tournament.party_id,
            user_id=db_notification.user_id,
            enabled=True,
        )
    ).all()


def _push_to_subscriptions(
    db_subscriptions, db_tournament, *, message, vapid_private_key, now
) -> tuple[bool, str | None]:
    """Return whether any browser got it, and the last temporary error.

    Subscriptions the push service no longer knows (404/410) are disabled.
    """
    delivered = False
    transient_error = None
    for db_subscription in db_subscriptions:
        try:
            if webpush is None:
                raise RuntimeError(
                    'pywebpush is not installed in this environment.'
                )

            webpush(
                subscription_info={
                    'endpoint': db_subscription.endpoint,
                    'keys': {
                        'p256dh': db_subscription.endpoint_p256dh,
                        'auth': db_subscription.endpoint_auth,
                    },
                },
                data=json.dumps(message),
                vapid_private_key=vapid_private_key,
                vapid_claims={
                    'sub': _build_browser_push_vapid_subject(
                        db_tournament.party_id, db_subscription.endpoint
                    ),
                },
            )
            delivered = True
        except WebPushException as exc:  # pragma: no branch
            status_code = getattr(
                getattr(exc, 'response', None), 'status_code', None
            )
            if status_code in {404, 410}:
                db_subscription.enabled = False
                db_subscription.updated_at = now
                continue
            transient_error = _format_browser_push_delivery_error(exc)
        except Exception as exc:  # pragma: no cover - delivery fallback
            transient_error = _format_browser_push_delivery_error(exc)
    return delivered, transient_error


def _build_browser_push_private_key_for_pywebpush(private_key: str) -> str:
    """Return a pywebpush-compatible VAPID private key string.

    Stored keys are PEM strings. `pywebpush` expects a PEM file path or a
    DER/base64 representation, not PEM contents directly.
    """
    normalized = private_key.strip()
    if 'BEGIN PRIVATE KEY' not in normalized:
        return normalized

    loaded_private_key = serialization.load_pem_private_key(
        normalized.encode('ascii'),
        password=None,
    )
    der = loaded_private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return urlsafe_b64encode(der).decode('ascii').rstrip('=')


def _build_browser_push_vapid_subject(
    party_id: PartyID, endpoint: str | None = None
) -> str:
    site_server_name = find_browser_push_site_server_name(party_id)
    if site_server_name:
        return f'https://{site_server_name}'

    server_name = str(current_app.config.get('SERVER_NAME') or '').strip()
    if server_name:
        host = server_name.split(':', 1)[0].strip()
        if host and host != 'localhost':
            return f'https://{host}'

    endpoint_host = _get_browser_push_endpoint_host(endpoint)
    if endpoint_host:
        return f'mailto:noreply@{endpoint_host}'

    return 'mailto:noreply@byceps.invalid'


def _get_browser_push_endpoint_host(endpoint: str | None) -> str | None:
    if not endpoint:
        return None

    try:
        return httpx.URL(endpoint).host
    except Exception:  # pragma: no cover - defensive fallback
        return None


def _format_browser_push_delivery_error(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f'{type(exc).__name__}: {message}'
    return type(exc).__name__

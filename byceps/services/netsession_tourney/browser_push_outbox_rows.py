"""
byceps.services.netsession_tourney.browser_push_outbox_rows
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Browser push outbox rows: loading the notification and the VAPID key
for a row, and settling it (sent, retry, dead letter).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from byceps.database import db

from .browser_push_service import (
    BROWSER_PUSH_MAX_ATTEMPTS,
    decrypt_browser_push_private_key,
)
from .dbmodels import (
    DbNetsessionTourneyBrowserPushConfig,
    DbNetsessionTourneyBrowserPushOutbox,
    DbNetsessionTourneyNotification,
    DbNetsessionTourneyTournament,
)
from .models import BrowserPushOutboxStatus


def _get_browser_push_row_notification(
    db_row, now: datetime
) -> (
    tuple[DbNetsessionTourneyNotification, DbNetsessionTourneyTournament] | None
):
    """Return the row's notification and tournament, or dead-letter the
    row and return `None` if one of them is gone."""
    db_notification = db.session.get(
        DbNetsessionTourneyNotification, db_row.notification_id
    )
    if db_notification is None:
        _mark_browser_push_outbox_dead_letter(
            db_row, 'Unknown notification.', now
        )
        return None

    db_tournament = db.session.get(
        DbNetsessionTourneyTournament, db_notification.tournament_id
    )
    if db_tournament is None:
        _mark_browser_push_outbox_dead_letter(
            db_row, 'Unbekanntes Turnier.', now
        )
        return None

    return db_notification, db_tournament


def _get_browser_push_private_key_pem(
    db_row, db_tournament: DbNetsessionTourneyTournament, now: datetime
) -> str | None:
    """Return the party's VAPID private key, or settle the row (sent if
    push is off, retry if the key is unusable) and return `None`."""
    db_config = db.session.get(
        DbNetsessionTourneyBrowserPushConfig, db_tournament.party_id
    )
    if (
        db_config is None
        or not db_config.enabled
        or not db_config.vapid_private_key_encrypted
    ):
        _mark_browser_push_sent(db_row)
        return None

    private_key_pem = decrypt_browser_push_private_key(
        db_config.vapid_private_key_encrypted
    )
    if private_key_pem is None:
        _schedule_browser_push_outbox_retry(
            db_row, 'No valid browser push private key configured.', now
        )
        return None

    return private_key_pem


def _mark_browser_push_sent(db_row) -> None:
    db_row.status = BrowserPushOutboxStatus.sent.value
    db_row.next_attempt_at = None
    db_row.last_error = None


def _mark_browser_push_outbox_dead_letter(
    db_row: DbNetsessionTourneyBrowserPushOutbox,
    reason: str,
    now: datetime,
) -> None:
    db_row.status = BrowserPushOutboxStatus.dead_letter.value
    db_row.next_attempt_at = None
    db_row.last_error = reason[:500]
    db_row.updated_at = now


def _schedule_browser_push_outbox_retry(
    db_row: DbNetsessionTourneyBrowserPushOutbox,
    reason: str,
    now: datetime,
) -> None:
    if db_row.attempt_count >= BROWSER_PUSH_MAX_ATTEMPTS:
        _mark_browser_push_outbox_dead_letter(
            db_row,
            f'Delivery failed repeatedly. Last error: {reason}',
            now,
        )
        return

    backoff_minutes = 2 ** min(db_row.attempt_count, 6)
    db_row.status = BrowserPushOutboxStatus.failed.value
    db_row.next_attempt_at = now + timedelta(minutes=backoff_minutes)
    db_row.last_error = reason[:500]
    db_row.updated_at = now

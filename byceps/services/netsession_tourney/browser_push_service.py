"""
byceps.services.netsession_tourney.browser_push_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Browser push: configuration (VAPID keys), subscriptions and recipients.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import UserID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .browser_push_config import (
    configure_browser_push as configure_browser_push,
    get_browser_push_config as get_browser_push_config,
    get_browser_push_public_key_for_party as get_browser_push_public_key_for_party,
    is_browser_push_enabled_for_party as is_browser_push_enabled_for_party,
    is_missing_browser_push_table_error as is_missing_browser_push_table_error,
)
from .browser_push_endpoint import validate_push_subscription
from .browser_push_keys import (
    decrypt_browser_push_private_key as decrypt_browser_push_private_key,
)
from .dbmodels import (
    DbNetsessionTourneyBrowserPushOutbox,
    DbNetsessionTourneyBrowserPushSubscription,
    DbNetsessionTourneyNotification,
)
from .models import (
    BrowserPushSubscriptionID,
    TournamentID,
)
from .notification_recipients import (
    get_active_user_ids_for_tournament,
)


BROWSER_PUSH_SUPPORTED_NOTIFICATION_KINDS = {
    'tournament_live',
    'tournament_closed',
    'tournament_canceled',
    'checkin_open',
    'manual_announcement',
    'match_ready',
    'flatout2_host_assigned',
    'result_submitted',
    'schedule_changed',
    'dispute_opened',
    'chat_message_posted',
}


BROWSER_PUSH_MAX_ATTEMPTS = 5


def upsert_browser_push_subscription(
    party_id: PartyID,
    user_id: UserID,
    *,
    endpoint: str,
    endpoint_p256dh: str,
    endpoint_auth: str,
    user_agent: str | None = None,
) -> Result[None, str]:
    if not is_browser_push_enabled_for_party(party_id):
        return Err('Browser-Benachrichtigungen sind ausgeschaltet.')

    endpoint = endpoint.strip()
    endpoint_p256dh = endpoint_p256dh.strip()
    endpoint_auth = endpoint_auth.strip()
    error = validate_push_subscription(endpoint, endpoint_p256dh, endpoint_auth)
    if error is not None:
        return Err(error)

    now = datetime.utcnow()
    try:
        db_subscription = db.session.scalar(
            select(DbNetsessionTourneyBrowserPushSubscription).filter_by(
                party_id=party_id,
                endpoint=endpoint,
            )
        )
    except DBAPIError as exc:
        if is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return Err(
                'Die Tabellen für Browser-Benachrichtigungen fehlen noch.'
            )
        raise
    if db_subscription is None:
        db_subscription = DbNetsessionTourneyBrowserPushSubscription(
            BrowserPushSubscriptionID(generate_uuid7()),
            party_id,
            user_id,
            endpoint,
            endpoint_p256dh,
            endpoint_auth,
            now,
            user_agent=_normalize_browser_push_user_agent(user_agent),
        )
        db.session.add(db_subscription)
    else:
        db_subscription.user_id = user_id
        db_subscription.endpoint_p256dh = endpoint_p256dh
        db_subscription.endpoint_auth = endpoint_auth
        db_subscription.user_agent = _normalize_browser_push_user_agent(
            user_agent
        )
        db_subscription.enabled = True
        db_subscription.last_seen_at = now
        db_subscription.updated_at = now

    db.session.commit()
    return Ok(None)


def _normalize_browser_push_user_agent(user_agent: str | None) -> str | None:
    return (user_agent or '').strip()[:500] or None


def disable_browser_push_subscription(
    party_id: PartyID,
    user_id: UserID,
    *,
    endpoint: str,
) -> None:
    try:
        db_subscription = db.session.scalar(
            select(DbNetsessionTourneyBrowserPushSubscription).filter_by(
                party_id=party_id,
                user_id=user_id,
                endpoint=endpoint.strip(),
            )
        )
    except DBAPIError as exc:
        if is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return
        raise
    if db_subscription is None:
        return

    db_subscription.enabled = False
    db_subscription.updated_at = datetime.utcnow()
    db.session.commit()


def has_active_browser_push_subscription_for_user(
    party_id: PartyID, user_id: UserID
) -> bool:
    return (
        count_active_browser_push_subscriptions_for_user(party_id, user_id) > 0
    )


def count_active_browser_push_subscriptions_for_user(
    party_id: PartyID, user_id: UserID
) -> int:
    try:
        count = db.session.scalar(
            select(
                db.func.count(DbNetsessionTourneyBrowserPushSubscription.id)
            ).filter_by(party_id=party_id, user_id=user_id, enabled=True)
        )
    except DBAPIError as exc:
        if is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return 0
        raise
    return int(count or 0)


def count_browser_push_subscribed_participants_for_tournament(
    party_id: PartyID, tournament_id: TournamentID
) -> int:
    user_ids, _subscription_count = (
        get_active_browser_push_subscription_recipients_for_tournament(
            party_id, tournament_id
        )
    )
    return len(user_ids)


def get_active_browser_push_subscription_recipients_for_tournament(
    party_id: PartyID,
    tournament_id: TournamentID,
) -> tuple[set[UserID], int]:
    user_ids = get_active_user_ids_for_tournament(tournament_id)
    if not user_ids:
        return set(), 0

    try:
        rows = db.session.execute(
            select(DbNetsessionTourneyBrowserPushSubscription.user_id)
            .filter_by(
                party_id=party_id,
                enabled=True,
            )
            .filter(
                DbNetsessionTourneyBrowserPushSubscription.user_id.in_(user_ids)
            )
        ).all()
    except DBAPIError as exc:
        if is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return set(), 0
        raise

    subscribed_user_ids = {user_id for (user_id,) in rows}
    return subscribed_user_ids, len(rows)


def get_browser_push_subscribed_user_ids_for_tournament(
    party_id: PartyID, tournament_id: TournamentID
) -> set[UserID]:
    user_ids = get_active_user_ids_for_tournament(tournament_id)
    if not user_ids:
        return set()

    try:
        rows = db.session.scalars(
            select(DbNetsessionTourneyBrowserPushSubscription.user_id)
            .filter_by(party_id=party_id, enabled=True)
            .filter(
                DbNetsessionTourneyBrowserPushSubscription.user_id.in_(user_ids)
            )
            .distinct()
        ).all()
    except DBAPIError as exc:
        if is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return set()
        raise

    return set(rows)


def get_recent_browser_push_outbox_entries_for_tournament(
    tournament_id: TournamentID,
    *,
    limit: int = 40,
) -> list[dict[str, Any]]:
    try:
        rows = db.session.execute(
            select(
                DbNetsessionTourneyBrowserPushOutbox,
                DbNetsessionTourneyNotification,
            )
            .join(
                DbNetsessionTourneyNotification,
                DbNetsessionTourneyNotification.id
                == DbNetsessionTourneyBrowserPushOutbox.notification_id,
            )
            .filter(
                DbNetsessionTourneyNotification.tournament_id == tournament_id
            )
            .order_by(DbNetsessionTourneyBrowserPushOutbox.created_at.desc())
            .limit(limit)
        ).all()
    except DBAPIError as exc:
        if is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return []
        raise

    entries = []
    for db_outbox, db_notification in rows:
        entries.append(
            _build_browser_push_outbox_entry(db_outbox, db_notification)
        )

    return entries


def _build_browser_push_outbox_entry(
    db_outbox: DbNetsessionTourneyBrowserPushOutbox,
    db_notification: DbNetsessionTourneyNotification,
) -> dict[str, Any]:
    payload = dict(db_notification.payload_json or {})
    return {
        'notification_id': db_notification.id,
        'user_id': db_notification.user_id,
        'kind': db_notification.kind,
        'title': _clean_browser_push_payload_text(payload, 'title'),
        'body': _clean_browser_push_payload_text(payload, 'body'),
        'status': db_outbox.status,
        'attempt_count': db_outbox.attempt_count,
        'next_attempt_at': db_outbox.next_attempt_at,
        'last_error': db_outbox.last_error,
        'created_at': db_outbox.created_at,
        'updated_at': db_outbox.updated_at,
    }


def _clean_browser_push_payload_text(
    payload: dict[str, Any], key: str
) -> str | None:
    return str(payload.get(key) or '').strip() or None

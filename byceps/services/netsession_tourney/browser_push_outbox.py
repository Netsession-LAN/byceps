"""
byceps.services.netsession_tourney.browser_push_outbox
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Browser push delivery: processing the outbox, message payloads, retries.
"""

from __future__ import annotations

from base64 import urlsafe_b64encode
from datetime import datetime, timedelta
import json
from typing import Any
from uuid import UUID

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

from .browser_push_service import (
    _decrypt_browser_push_private_key,
    _is_missing_browser_push_table_error,
    BROWSER_PUSH_MAX_ATTEMPTS,
)
from .dbmodels import (
    DbNetsessionTourneyBrowserPushConfig,
    DbNetsessionTourneyBrowserPushOutbox,
    DbNetsessionTourneyBrowserPushSubscription,
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyNotification,
    DbNetsessionTourneyStage,
    DbNetsessionTourneyTournament,
)
from .models import (
    BrowserPushOutboxStatus,
    MatchID,
    StageType,
)
from .notification_labels import (
    _build_double_elimination_notification_match_label,
)
from .notification_urls import (
    _build_browser_push_badge_url,
    _build_browser_push_logo_urls,
    _find_browser_push_site_server_name,
)
from .tournament_queries import (
    _build_flatout2_first_race_summary,
)


def process_browser_push_outbox(*, limit: int = 50) -> int:
    now = datetime.utcnow()
    try:
        db_rows = _load_due_browser_push_rows(now, limit)
    except DBAPIError as exc:
        if _is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return 0
        raise

    for db_row in db_rows:
        db_row.attempt_count += 1
        db_row.updated_at = now
        _deliver_browser_push_row(db_row, now)

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
    db_notification = db.session.get(
        DbNetsessionTourneyNotification, db_row.notification_id
    )
    if db_notification is None:
        _mark_browser_push_outbox_dead_letter(db_row, 'Unknown notification.', now)
        return

    db_tournament = db.session.get(
        DbNetsessionTourneyTournament, db_notification.tournament_id
    )
    if db_tournament is None:
        _mark_browser_push_outbox_dead_letter(db_row, 'Unbekanntes Turnier.', now)
        return

    db_config = db.session.get(
        DbNetsessionTourneyBrowserPushConfig, db_tournament.party_id
    )
    if (
        db_config is None
        or not db_config.enabled
        or not db_config.vapid_private_key_encrypted
    ):
        _mark_browser_push_sent(db_row)
        return

    private_key_pem = _decrypt_browser_push_private_key(
        db_config.vapid_private_key_encrypted
    )
    if private_key_pem is None:
        _schedule_browser_push_outbox_retry(
            db_row, 'No valid browser push private key configured.', now
        )
        return

    db_subscriptions = db.session.scalars(
        select(DbNetsessionTourneyBrowserPushSubscription).filter_by(
            party_id=db_tournament.party_id,
            user_id=db_notification.user_id,
            enabled=True,
        )
    ).all()
    if not db_subscriptions:
        _mark_browser_push_sent(db_row)
        return

    delivered, transient_error = _push_to_subscriptions(
        db_subscriptions,
        db_tournament,
        message=_build_browser_push_message_payload(db_tournament, db_notification),
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
                raise RuntimeError('pywebpush is not installed in this environment.')

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
            status_code = getattr(getattr(exc, 'response', None), 'status_code', None)
            if status_code in {404, 410}:
                db_subscription.enabled = False
                db_subscription.updated_at = now
                continue
            transient_error = _format_browser_push_delivery_error(exc)
        except Exception as exc:  # pragma: no cover - delivery fallback
            transient_error = _format_browser_push_delivery_error(exc)
    return delivered, transient_error


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


def _build_browser_push_message_payload(
    db_tournament: DbNetsessionTourneyTournament,
    db_notification: DbNetsessionTourneyNotification,
) -> dict[str, Any]:
    payload = dict(db_notification.payload_json or {})
    kind = db_notification.kind
    match_label = _build_browser_push_match_label(payload)
    title = str(payload.get('title') or '').strip() or db_tournament.title

    body = _build_browser_push_body(kind, payload, match_label)

    url = payload.get('url')
    if not isinstance(url, str) or not url:
        url = f'/ns-tourneys/{db_tournament.slug}'

    if kind == 'manual_announcement':
        tag_suffix = db_notification.id
        renotify = True
    else:
        tag_suffix = (
            payload.get('match_id') or payload.get('slug') or db_tournament.id
        )
        renotify = False

    icon_url, image_url = _build_browser_push_logo_urls(db_tournament)
    return {
        'title': title,
        'body': body[:180],
        'url': url,
        'tag': f'netsession-tourney-{kind}-{tag_suffix}',
        'renotify': renotify,
        'icon': icon_url,
        'badge': _build_browser_push_badge_url(),
        'image': image_url,
    }


def _build_browser_push_body(
    kind: str, payload: dict[str, Any], match_label: str | None
) -> str:
    if kind == 'tournament_live':
        body = 'Turnier ist jetzt live.'
    elif kind == 'tournament_closed':
        body = 'Turnier wurde beendet.'
    elif kind == 'tournament_canceled':
        body = 'Turnier wurde abgesagt.'
    elif kind == 'manual_announcement':
        body = str(payload.get('body') or '').strip() or 'Es gibt ein neues Turnier-Update.'
    elif kind == 'match_ready':
        body = (
            f'{match_label} ist spielbereit.'
            if match_label
            else 'Dein Match ist spielbereit.'
        )
    elif kind == 'flatout2_host_assigned':
        first_race_summary = _build_flatout2_first_race_summary(payload)
        base_body = (
            f'Du wurdest als Host für {match_label} ausgewählt.'
            if match_label
            else 'Du wurdest als Host für ein Match ausgewählt.'
        )
        body = (
            f'{base_body} {first_race_summary}'
            if first_race_summary
            else base_body
        )
    elif kind == 'result_submitted':
        body = (
            f'{match_label}: Ergebnis wurde übermittelt.'
            if match_label
            else 'Für dein Match wurde ein Ergebnis übermittelt.'
        )
    elif kind == 'schedule_changed':
        body = (
            f'{match_label}: Matchzeit wurde geändert.'
            if match_label
            else 'Die Matchzeit wurde geändert.'
        )
    elif kind == 'dispute_opened':
        body = (
            f'{match_label}: Streitfall wurde geöffnet.'
            if match_label
            else 'Für dein Match wurde ein Streitfall geöffnet.'
        )
    elif kind == 'chat_message_posted':
        body = _build_browser_push_chat_body(payload, match_label)
    else:
        body = 'Es gibt ein neues Update.'
    return body


def _build_browser_push_chat_body(
    payload: dict[str, Any], match_label: str | None
) -> str:
    body_preview = str(payload.get('body_preview') or '').strip()
    return (
        (
            f'{match_label}: Neue Nachricht - {body_preview}'
            if match_label
            else f'Neue Match-Nachricht: {body_preview}'
        )
        if body_preview
        else (
            f'{match_label}: Neue Match-Nachricht.'
            if match_label
            else 'Neue Match-Nachricht.'
        )
    )


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
    site_server_name = _find_browser_push_site_server_name(party_id)
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


def _build_browser_push_match_label(payload: dict[str, Any]) -> str | None:
    match_id = payload.get('match_id')
    if not isinstance(match_id, str) or not match_id:
        return None

    try:
        parsed_match_id = MatchID(UUID(match_id))
    except ValueError:
        return None

    db_match = db.session.get(DbNetsessionTourneyMatch, parsed_match_id)
    if db_match is None:
        return None

    db_stage = db.session.get(DbNetsessionTourneyStage, db_match.stage_id)
    if db_stage is None:
        return f'M #{db_match.match_no}'

    if db_stage.type in {
        StageType.double_elimination,
        StageType.double_elimination_double_grand_final,
    }:
        return _build_double_elimination_notification_match_label(
            db_match, db_stage.id
        )

    generic_stage_names = {'match', 'matches'}
    stage_settings = db_stage.settings_json or {}
    builder_display_title = str(stage_settings.get('builder_display_title') or '').strip()
    if builder_display_title:
        return f'{builder_display_title} • M #{db_match.match_no}'

    if db_stage.name:
        stage_name = db_stage.name.strip()
        if stage_name.lower() not in generic_stage_names:
            return f'{stage_name} • M #{db_match.match_no}'

    return f'M #{db_match.match_no}'


def _format_browser_push_delivery_error(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f'{type(exc).__name__}: {message}'
    return type(exc).__name__

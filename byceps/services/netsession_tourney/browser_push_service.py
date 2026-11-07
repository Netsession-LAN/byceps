"""
byceps.services.netsession_tourney.browser_push_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Browser push: configuration (VAPID keys), subscriptions and recipients.
"""

from __future__ import annotations

from base64 import urlsafe_b64encode
from datetime import datetime
from hashlib import sha256
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from flask import current_app
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from byceps.database import db
from byceps.services.party.dbmodels import DbParty
from byceps.services.party.models import PartyID
from byceps.services.user.models import UserID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .browser_push_endpoint import validate_push_subscription
from .dbmodels import (
    DbNetsessionTourneyBrowserPushConfig,
    DbNetsessionTourneyBrowserPushOutbox,
    DbNetsessionTourneyBrowserPushSubscription,
    DbNetsessionTourneyNotification,
)
from .models import (
    BrowserPushConfig,
    BrowserPushSubscriptionID,
    TournamentID,
)
from .service_helpers import (
    db_browser_push_config_to_model,
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


def get_browser_push_config(party_id: PartyID) -> BrowserPushConfig:
    try:
        db_config = db.session.get(DbNetsessionTourneyBrowserPushConfig, party_id)
    except DBAPIError as exc:
        if is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return _build_default_browser_push_config(party_id)
        raise

    if db_config is None:
        return _build_default_browser_push_config(party_id)

    return db_browser_push_config_to_model(db_config)


def is_browser_push_enabled_for_party(party_id: PartyID) -> bool:
    try:
        db_config = db.session.get(DbNetsessionTourneyBrowserPushConfig, party_id)
    except DBAPIError as exc:
        if is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return False
        raise

    return bool(db_config and db_config.enabled and db_config.vapid_public_key)


def get_browser_push_public_key_for_party(party_id: PartyID) -> str | None:
    try:
        db_config = db.session.get(DbNetsessionTourneyBrowserPushConfig, party_id)
    except DBAPIError as exc:
        if is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return None
        raise

    if db_config is None or not db_config.enabled:
        return None

    return db_config.vapid_public_key


def configure_browser_push(
    party_id: PartyID,
    *,
    enabled: bool,
) -> Result[BrowserPushConfig, str]:
    db_party = db.session.get(DbParty, party_id)
    if db_party is None:
        return Err('Unbekannte Party.')

    try:
        db_config = db.session.get(DbNetsessionTourneyBrowserPushConfig, party_id)
    except DBAPIError as exc:
        if is_missing_browser_push_table_error(exc):
            db.session.rollback()
            return Err('Die Tabellen für Browser-Benachrichtigungen fehlen noch.')
        raise

    now = datetime.utcnow()
    if db_config is None:
        db_config = DbNetsessionTourneyBrowserPushConfig(party_id, now)
        db.session.add(db_config)

    if enabled and (
        not db_config.vapid_public_key
        or not db_config.vapid_private_key_encrypted
    ):
        private_key_pem = _generate_browser_push_private_key_pem()
        db_config.vapid_public_key = _derive_browser_push_public_key(
            private_key_pem
        )
        db_config.vapid_private_key_encrypted = _encrypt_browser_push_private_key(
            private_key_pem
        )

    db_config.enabled = enabled
    db_config.updated_at = now
    db.session.commit()

    return Ok(db_browser_push_config_to_model(db_config))


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
            return Err('Die Tabellen für Browser-Benachrichtigungen fehlen noch.')
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
            user_agent=(user_agent or '').strip()[:500] or None,
        )
        db.session.add(db_subscription)
    else:
        db_subscription.user_id = user_id
        db_subscription.endpoint_p256dh = endpoint_p256dh
        db_subscription.endpoint_auth = endpoint_auth
        db_subscription.user_agent = (user_agent or '').strip()[:500] or None
        db_subscription.enabled = True
        db_subscription.last_seen_at = now
        db_subscription.updated_at = now

    db.session.commit()
    return Ok(None)


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
    return count_active_browser_push_subscriptions_for_user(
        party_id, user_id
    ) > 0


def count_active_browser_push_subscriptions_for_user(
    party_id: PartyID, user_id: UserID
) -> int:
    try:
        count = db.session.scalar(
            select(db.func.count(DbNetsessionTourneyBrowserPushSubscription.id))
            .filter_by(party_id=party_id, user_id=user_id, enabled=True)
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
            select(DbNetsessionTourneyBrowserPushSubscription.user_id).filter_by(
                party_id=party_id,
                enabled=True,
            ).filter(
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
            .filter(DbNetsessionTourneyNotification.tournament_id == tournament_id)
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
        payload = dict(db_notification.payload_json or {})
        entries.append(
            {
                'notification_id': db_notification.id,
                'user_id': db_notification.user_id,
                'kind': db_notification.kind,
                'title': str(payload.get('title') or '').strip() or None,
                'body': str(payload.get('body') or '').strip() or None,
                'status': db_outbox.status,
                'attempt_count': db_outbox.attempt_count,
                'next_attempt_at': db_outbox.next_attempt_at,
                'last_error': db_outbox.last_error,
                'created_at': db_outbox.created_at,
                'updated_at': db_outbox.updated_at,
            }
        )

    return entries


def _get_browser_push_fernet() -> Fernet:
    secret_key = current_app.config['SECRET_KEY']
    if isinstance(secret_key, str):
        raw = secret_key.encode('utf-8')
    else:
        raw = bytes(secret_key)

    key = urlsafe_b64encode(sha256(raw + b'browser-push').digest())
    return Fernet(key)


def _get_browser_push_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(
        current_app.config['SECRET_KEY'], salt='netsession_tourney.browser_push'
    )


def _generate_browser_push_private_key_pem() -> str:
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode('ascii')


def _derive_browser_push_public_key(private_key_pem: str) -> str:
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode('ascii'), password=None
    )
    public_key = private_key.public_key()
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return (
        urlsafe_b64encode(public_key_bytes).decode('ascii').rstrip('=')
    )


def _encrypt_browser_push_private_key(private_key_pem: str) -> str:
    token = _get_browser_push_fernet().encrypt(
        private_key_pem.encode('utf-8')
    )
    return token.decode('ascii')


def decrypt_browser_push_private_key(token: str) -> str | None:
    try:
        decrypted = _get_browser_push_fernet().decrypt(token.encode('ascii'))
        return decrypted.decode('utf-8')
    except (InvalidToken, UnicodeDecodeError):
        try:
            data = _get_browser_push_serializer().loads(token)
        except BadSignature:
            return None

        private_key_pem = data.get('private_key_pem')
        return private_key_pem if isinstance(private_key_pem, str) else None


def _build_default_browser_push_config(
    party_id: PartyID,
) -> BrowserPushConfig:
    now = datetime.utcnow()
    return BrowserPushConfig(
        party_id=party_id,
        enabled=False,
        vapid_public_key=None,
        created_at=now,
        updated_at=now,
    )


def is_missing_browser_push_table_error(exc: DBAPIError) -> bool:
    sqlstate = getattr(getattr(exc, 'orig', None), 'sqlstate', None)
    if sqlstate != '42P01':
        return False

    statement = str(getattr(exc, 'statement', '') or '')
    return 'netsession_tourney_browser_push_' in statement

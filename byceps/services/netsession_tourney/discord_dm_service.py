"""
byceps.services.netsession_tourney.discord_dm_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Discord direct messages: bot configuration, token encryption, subscriptions.
"""

from __future__ import annotations

from base64 import urlsafe_b64encode
from collections.abc import Sequence
from datetime import datetime
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from byceps.database import db
from byceps.services.external_accounts import external_accounts_service
from byceps.services.party.dbmodels import DbParty
from byceps.services.party.models import PartyID
from byceps.services.user.models import UserID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyDiscordDmConfig,
    DbNetsessionTourneyDiscordDmSubscription,
)
from .discord_ids import is_discord_id
from .models import (
    DiscordDmConfig,
    DiscordDmSubscriptionID,
)
from .service_helpers import (
    db_discord_dm_config_to_model,
)


DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS = {
    'tournament_live',
    'tournament_canceled',
    'checkin_open',
    'match_ready',
    'flatout2_host_assigned',
    'result_submitted',
}


DISCORD_DM_MAX_ATTEMPTS = 5


DISCORD_DM_TIMEOUT_SECONDS = 10


def get_discord_dm_config(party_id: PartyID) -> DiscordDmConfig:
    try:
        db_config = db.session.get(DbNetsessionTourneyDiscordDmConfig, party_id)
    except DBAPIError as exc:
        if is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return _build_default_discord_dm_config(party_id)
        raise

    if db_config is None:
        return _build_default_discord_dm_config(party_id)

    return db_discord_dm_config_to_model(db_config)


def is_discord_dm_enabled_for_party(party_id: PartyID) -> bool:
    try:
        db_config = db.session.get(DbNetsessionTourneyDiscordDmConfig, party_id)
    except DBAPIError as exc:
        if is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return False
        raise

    return bool(
        db_config
        and db_config.enabled
        and db_config.application_id
        and db_config.bot_token_encrypted
    )


def configure_discord_dm(
    party_id: PartyID,
    *,
    enabled: bool,
    application_id: str | None,
    bot_token: str | None,
    default_event_mask: list[str],
) -> Result[DiscordDmConfig, str]:
    db_party = db.session.get(DbParty, party_id)
    if db_party is None:
        return Err('Unbekannte Party.')

    try:
        db_config = db.session.get(DbNetsessionTourneyDiscordDmConfig, party_id)
    except DBAPIError as exc:
        if is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return Err('Discord-DM-Tabellen sind noch nicht installiert.')
        raise

    return _store_discord_dm_config(
        party_id,
        db_config,
        enabled=enabled,
        application_id=application_id,
        bot_token=bot_token,
        default_event_mask=default_event_mask,
    )


def _store_discord_dm_config(
    party_id: PartyID,
    db_config: DbNetsessionTourneyDiscordDmConfig | None,
    *,
    enabled: bool,
    application_id: str | None,
    bot_token: str | None,
    default_event_mask: list[str],
) -> Result[DiscordDmConfig, str]:
    normalized_application_id = _normalize_discord_dm_text(application_id)
    normalized_bot_token = _normalize_discord_dm_text(bot_token)
    normalized_event_mask = _normalize_discord_dm_event_mask(default_event_mask)

    error = _validate_discord_dm_application_id(
        enabled, normalized_application_id
    )
    if error is not None:
        return Err(error)

    now = datetime.utcnow()
    if db_config is None:
        db_config = DbNetsessionTourneyDiscordDmConfig(party_id, now)
        db.session.add(db_config)

    if _is_discord_dm_bot_token_missing(
        enabled, normalized_bot_token, db_config
    ):
        return Err('Ein Bot-Token ist erforderlich.')

    db_config.enabled = enabled
    db_config.application_id = normalized_application_id
    if normalized_bot_token:
        db_config.bot_token_encrypted = _encrypt_discord_dm_bot_token(
            normalized_bot_token
        )
    db_config.default_event_mask = normalized_event_mask
    db_config.updated_at = now
    db.session.commit()

    return Ok(db_discord_dm_config_to_model(db_config))


def _normalize_discord_dm_text(value: str | None) -> str | None:
    return (value or '').strip() or None


def _normalize_discord_dm_event_mask(
    default_event_mask: list[str],
) -> list[str]:
    return sorted(
        {
            item
            for item in default_event_mask
            if item in DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS
        }
    )


def _validate_discord_dm_application_id(
    enabled: bool, normalized_application_id: str | None
) -> str | None:
    if enabled and not normalized_application_id:
        return 'Eine Application ID ist erforderlich.'
    if normalized_application_id and not is_discord_id(
        normalized_application_id
    ):
        return 'Die Application ID muss aus 17 bis 20 Ziffern bestehen.'
    return None


def _is_discord_dm_bot_token_missing(
    enabled: bool,
    normalized_bot_token: str | None,
    db_config: DbNetsessionTourneyDiscordDmConfig,
) -> bool:
    return bool(
        enabled
        and not normalized_bot_token
        and not db_config.bot_token_encrypted
    )


def get_masked_discord_dm_bot_token(party_id: PartyID) -> str:
    try:
        db_config = db.session.get(DbNetsessionTourneyDiscordDmConfig, party_id)
    except DBAPIError as exc:
        if is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return ''
        raise

    if db_config is None or not db_config.bot_token_encrypted:
        return ''

    return _mask_discord_dm_bot_token(
        decrypt_discord_dm_bot_token(db_config.bot_token_encrypted)
    )


def get_configured_discord_bot_credentials() -> Result[
    tuple[str, str] | None, str
]:
    try:
        db_configs = db.session.scalars(
            select(DbNetsessionTourneyDiscordDmConfig)
        ).all()
    except DBAPIError as exc:
        if is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return Ok(None)
        raise

    credentials = _collect_discord_bot_credentials(db_configs)

    if not credentials:
        return Ok(None)

    if len(credentials) > 1:
        return Err(
            'Mehrere unterschiedliche Discord-Bot-Konfigurationen sind aktiv.'
        )

    return Ok(next(iter(credentials)))


def get_enabled_discord_dm_bot_credentials() -> Result[
    tuple[str, str] | None, str
]:
    match get_configured_discord_bot_credentials():
        case Err(message):
            return Err(message)
        case Ok(None):
            return Ok(None)
        case Ok(credentials):
            pass

    return _confirm_enabled_discord_bot_credentials(credentials)


def _confirm_enabled_discord_bot_credentials(
    credentials: tuple[str, str],
) -> Result[tuple[str, str] | None, str]:
    try:
        db_configs = db.session.scalars(
            select(DbNetsessionTourneyDiscordDmConfig).filter_by(enabled=True)
        ).all()
    except DBAPIError as exc:
        if is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return Ok(None)
        raise

    enabled_credentials = _collect_discord_bot_credentials(db_configs)

    if not enabled_credentials:
        return Ok(None)

    return Ok(credentials)


def _collect_discord_bot_credentials(
    db_configs: Sequence[DbNetsessionTourneyDiscordDmConfig],
) -> set[tuple[str, str]]:
    credentials: set[tuple[str, str]] = set()
    for db_config in db_configs:
        if not db_config.application_id or not db_config.bot_token_encrypted:
            continue

        bot_token = decrypt_discord_dm_bot_token(db_config.bot_token_encrypted)
        if not bot_token:
            continue

        credentials.add((db_config.application_id, bot_token))

    return credentials


def upsert_discord_dm_subscription(
    party_id: PartyID,
    user_id: UserID,
) -> Result[None, str]:
    if not is_discord_dm_enabled_for_party(party_id):
        return Err('Discord-Benachrichtigungen sind deaktiviert.')

    connected_account = external_accounts_service.find_connected_external_account_for_user_and_service(
        user_id, 'discord'
    )
    if connected_account is None or not connected_account.external_id:
        return Err('Bitte verbinde zuerst deinen Discord-Account.')

    now = datetime.utcnow()
    try:
        db_subscription = db.session.scalar(
            select(DbNetsessionTourneyDiscordDmSubscription).filter_by(
                party_id=party_id,
                user_id=user_id,
            )
        )
    except DBAPIError as exc:
        if is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return Err('Discord-DM-Tabellen sind noch nicht installiert.')
        raise

    if db_subscription is None:
        db_subscription = DbNetsessionTourneyDiscordDmSubscription(
            DiscordDmSubscriptionID(generate_uuid7()),
            party_id,
            user_id,
            now,
        )
        db.session.add(db_subscription)
    else:
        db_subscription.enabled = True
        db_subscription.last_seen_at = now
        db_subscription.updated_at = now

    db.session.commit()
    return Ok(None)


def disable_discord_dm_subscription(
    party_id: PartyID,
    user_id: UserID,
) -> None:
    try:
        db_subscription = db.session.scalar(
            select(DbNetsessionTourneyDiscordDmSubscription).filter_by(
                party_id=party_id,
                user_id=user_id,
            )
        )
    except DBAPIError as exc:
        if is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return
        raise
    if db_subscription is None:
        return

    db_subscription.enabled = False
    db_subscription.updated_at = datetime.utcnow()
    db.session.commit()


def has_active_discord_dm_subscription_for_user(
    party_id: PartyID, user_id: UserID
) -> bool:
    return count_active_discord_dm_subscriptions_for_user(party_id, user_id) > 0


def count_active_discord_dm_subscriptions_for_user(
    party_id: PartyID, user_id: UserID
) -> int:
    try:
        count = db.session.scalar(
            select(
                db.func.count(DbNetsessionTourneyDiscordDmSubscription.id)
            ).filter_by(party_id=party_id, user_id=user_id, enabled=True)
        )
    except DBAPIError as exc:
        if is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return 0
        raise

    return int(count or 0)


def _get_discord_dm_fernet() -> Fernet:
    secret_key = current_app.config['SECRET_KEY']
    if isinstance(secret_key, str):
        raw = secret_key.encode('utf-8')
    else:
        raw = bytes(secret_key)

    key = urlsafe_b64encode(sha256(raw + b'discord-dm').digest())
    return Fernet(key)


def _encrypt_discord_dm_bot_token(bot_token: str) -> str:
    token = _get_discord_dm_fernet().encrypt(bot_token.encode('utf-8'))
    return token.decode('ascii')


def decrypt_discord_dm_bot_token(token: str | None) -> str | None:
    if not token:
        return None

    try:
        decrypted = _get_discord_dm_fernet().decrypt(token.encode('ascii'))
    except InvalidToken, ValueError:
        return None

    return decrypted.decode('utf-8')


def _mask_discord_dm_bot_token(bot_token: str | None) -> str:
    if not bot_token:
        return ''
    if len(bot_token) < 10:
        return '***'
    return bot_token[:6] + '***' + bot_token[-4:]


def _build_default_discord_dm_config(
    party_id: PartyID,
) -> DiscordDmConfig:
    now = datetime.utcnow()
    return DiscordDmConfig(
        party_id=party_id,
        enabled=False,
        application_id=None,
        default_event_mask=[],
        created_at=now,
        updated_at=now,
    )


def is_missing_discord_dm_table_error(exc: DBAPIError) -> bool:
    sqlstate = getattr(getattr(exc, 'orig', None), 'sqlstate', None)
    if sqlstate != '42P01':
        return False

    statement = str(getattr(exc, 'statement', '') or '')
    return 'netsession_tourney_discord_dm_' in statement

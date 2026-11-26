"""
byceps.services.netsession_tourney.discord_dm_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Discord direct messages: bot configuration, token encryption, subscriptions.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from byceps.database import db
from byceps.services.external_accounts import external_accounts_service
from byceps.services.party.models import PartyID
from byceps.services.user.models import UserID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyDiscordDmConfig,
    DbNetsessionTourneyDiscordDmSubscription,
)
from .discord_dm_config import (
    configure_discord_dm as configure_discord_dm,
    DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS as DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS,
    get_discord_dm_config as get_discord_dm_config,
    is_missing_discord_dm_table_error as is_missing_discord_dm_table_error,
)
from .discord_dm_credentials import (
    get_configured_discord_bot_credentials as get_configured_discord_bot_credentials,
    get_masked_discord_dm_bot_token as get_masked_discord_dm_bot_token,
)
from .discord_dm_token import (
    decrypt_discord_dm_bot_token as decrypt_discord_dm_bot_token,
)
from .models import (
    DiscordDmSubscriptionID,
)


DISCORD_DM_MAX_ATTEMPTS = 5


DISCORD_DM_TIMEOUT_SECONDS = 10


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

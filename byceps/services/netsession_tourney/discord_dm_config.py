"""
byceps.services.netsession_tourney.discord_dm_config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Party configuration of Discord direct messages.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import DBAPIError

from byceps.database import db
from byceps.services.party.dbmodels import DbParty
from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyDiscordDmConfig,
)
from .discord_dm_token import (
    _encrypt_discord_dm_bot_token,
)
from .discord_ids import is_discord_id
from .models import (
    DiscordDmConfig,
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

    # Check before creating a new config object, so a rejected config
    # does not stay in the database session.
    if _is_discord_dm_bot_token_missing(
        enabled, normalized_bot_token, db_config
    ):
        return Err('Ein Bot-Token ist erforderlich.')

    now = datetime.utcnow()
    if db_config is None:
        db_config = DbNetsessionTourneyDiscordDmConfig(party_id, now)
        db.session.add(db_config)

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
    db_config: DbNetsessionTourneyDiscordDmConfig | None,
) -> bool:
    has_stored_token = (
        db_config is not None and bool(db_config.bot_token_encrypted)
    )
    return bool(enabled and not normalized_bot_token and not has_stored_token)


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

"""
byceps.services.netsession_tourney.discord_dm_credentials
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Discord bot credentials from the Discord DM configuration.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyDiscordDmConfig,
)
from .discord_dm_config import (
    is_missing_discord_dm_table_error,
)
from .discord_dm_token import (
    _mask_discord_dm_bot_token,
    decrypt_discord_dm_bot_token,
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

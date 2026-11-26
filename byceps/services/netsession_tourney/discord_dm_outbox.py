"""
byceps.services.netsession_tourney.discord_dm_outbox
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Discord direct message delivery: processing the outbox, message payloads, test message.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from byceps.database import db
from byceps.services.external_accounts import external_accounts_service
from byceps.services.party.models import PartyID
from byceps.services.user.models import UserID
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyDiscordDmConfig,
    DbNetsessionTourneyDiscordDmOutbox,
    DbNetsessionTourneyNotification,
    DbNetsessionTourneyTournament,
)
from .discord_dm_payloads import (
    _build_discord_dm_message_payload,
    _build_test_discord_dm_message_payload,
)
from .discord_dm_service import (
    decrypt_discord_dm_bot_token,
    DISCORD_DM_MAX_ATTEMPTS,
    DISCORD_DM_TIMEOUT_SECONDS,
    is_missing_discord_dm_table_error,
)
from .models import (
    DiscordDmOutboxStatus,
)
from .outbox_processing import process_outbox_rows


def process_discord_dm_outbox(*, limit: int = 50) -> int:
    now = datetime.utcnow()
    try:
        db_rows = _load_due_discord_dm_outbox_rows(now, limit)
    except DBAPIError as exc:
        if is_missing_discord_dm_table_error(exc):
            db.session.rollback()
            return 0
        raise

    process_outbox_rows(
        db_rows,
        _deliver_discord_dm_outbox_row,
        _mark_discord_dm_outbox_dead_letter,
        now,
        outbox_name='discord_dm',
    )
    db.session.commit()
    return len(db_rows)


def _load_due_discord_dm_outbox_rows(now: datetime, limit: int):
    return db.session.scalars(
        select(DbNetsessionTourneyDiscordDmOutbox)
        .filter(
            DbNetsessionTourneyDiscordDmOutbox.status.in_(
                [
                    DiscordDmOutboxStatus.pending.value,
                    DiscordDmOutboxStatus.failed.value,
                ]
            )
        )
        .filter(
            (DbNetsessionTourneyDiscordDmOutbox.next_attempt_at.is_(None))
            | (DbNetsessionTourneyDiscordDmOutbox.next_attempt_at <= now)
        )
        .order_by(DbNetsessionTourneyDiscordDmOutbox.created_at.asc())
        .limit(limit)
    ).all()


def _deliver_discord_dm_outbox_row(
    db_row: DbNetsessionTourneyDiscordDmOutbox, now: datetime
) -> None:
    """Send one notification as Discord DM, or schedule a retry
    (temporary problem) or give up (dead letter)."""
    db_notification = db.session.get(
        DbNetsessionTourneyNotification, db_row.notification_id
    )
    if db_notification is None:
        _mark_discord_dm_outbox_dead_letter(
            db_row, 'Unknown notification.', now
        )
        return

    db_tournament = db.session.get(
        DbNetsessionTourneyTournament, db_notification.tournament_id
    )
    if db_tournament is None:
        _mark_discord_dm_outbox_dead_letter(
            db_row, 'Unknown tournament for Discord-DM outbox item.', now
        )
        return

    db_config = db.session.get(
        DbNetsessionTourneyDiscordDmConfig, db_tournament.party_id
    )
    if not _is_discord_dm_config_complete(db_config):
        _mark_discord_dm_outbox_dead_letter(
            db_row, 'Discord-DM-Konfiguration ist unvollständig.', now
        )
        return

    bot_token = decrypt_discord_dm_bot_token(db_config.bot_token_encrypted)
    if not bot_token:
        _mark_discord_dm_outbox_dead_letter(
            db_row, 'Kein gültiges Discord-Bot-Token konfiguriert.', now
        )
        return

    discord_user_id = _find_discord_user_id(db_notification.user_id)
    if not discord_user_id:
        _mark_discord_dm_outbox_dead_letter(
            db_row, 'Empfänger hat keinen verbundenen Discord-Account.', now
        )
        return

    payload = _build_discord_dm_message_payload(db_tournament, db_notification)

    _send_discord_dm_for_outbox_row(
        db_row, db_config, bot_token, discord_user_id, payload, now
    )


def _send_discord_dm_for_outbox_row(
    db_row: DbNetsessionTourneyDiscordDmOutbox,
    db_config: DbNetsessionTourneyDiscordDmConfig,
    bot_token: str,
    discord_user_id: str,
    payload: dict[str, Any],
    now: datetime,
) -> None:
    try:
        _send_discord_dm(
            application_id=db_config.application_id,
            bot_token=bot_token,
            discord_user_id=discord_user_id,
            payload=payload,
        )
    except httpx.HTTPError as exc:
        _schedule_discord_dm_outbox_retry(
            db_row,
            f'Discord-DM-Anfrage fehlgeschlagen: {type(exc).__name__}',
            now,
        )
        return
    except ValueError as exc:
        _mark_discord_dm_outbox_dead_letter(db_row, str(exc), now)
        return

    db_row.status = DiscordDmOutboxStatus.sent.value
    db_row.next_attempt_at = None
    db_row.last_error = None


def _is_discord_dm_config_complete(
    db_config: DbNetsessionTourneyDiscordDmConfig | None,
) -> bool:
    return not (
        db_config is None
        or not db_config.enabled
        or not db_config.application_id
        or not db_config.bot_token_encrypted
    )


def _find_discord_user_id(user_id: UserID) -> str | None:
    connected_account = external_accounts_service.find_connected_external_account_for_user_and_service(
        user_id, 'discord'
    )
    return (
        connected_account.external_id if connected_account is not None else None
    )


def send_test_discord_dm(
    party_id: PartyID,
    user_id: UserID,
) -> Result[None, str]:
    db_config = db.session.get(DbNetsessionTourneyDiscordDmConfig, party_id)
    if db_config is None or not db_config.enabled:
        return Err('Discord-Privatbenachrichtigungen sind nicht aktiviert.')

    if not db_config.application_id or not db_config.bot_token_encrypted:
        return Err('Discord-DM-Konfiguration ist unvollständig.')

    return _send_test_discord_dm_with_config(party_id, user_id, db_config)


def _send_test_discord_dm_with_config(
    party_id: PartyID,
    user_id: UserID,
    db_config: DbNetsessionTourneyDiscordDmConfig,
) -> Result[None, str]:
    discord_user_id = _find_discord_user_id(user_id)
    if not discord_user_id:
        return Err('Dein Benutzerkonto hat keinen verbundenen Discord-Account.')

    bot_token = decrypt_discord_dm_bot_token(db_config.bot_token_encrypted)
    if not bot_token:
        return Err('Kein gültiges Discord-Bot-Token konfiguriert.')

    payload = _build_test_discord_dm_message_payload(party_id)

    try:
        _send_discord_dm(
            application_id=db_config.application_id,
            bot_token=bot_token,
            discord_user_id=discord_user_id,
            payload=payload,
        )
    except httpx.HTTPError as exc:
        return Err(f'Discord-DM-Anfrage fehlgeschlagen: {type(exc).__name__}')
    except ValueError as exc:
        return Err(str(exc))

    return Ok(None)


def _mark_discord_dm_outbox_dead_letter(
    db_row: DbNetsessionTourneyDiscordDmOutbox,
    reason: str,
    now: datetime,
) -> None:
    db_row.status = DiscordDmOutboxStatus.dead_letter.value
    db_row.next_attempt_at = None
    db_row.last_error = reason[:500]
    db_row.updated_at = now


def _schedule_discord_dm_outbox_retry(
    db_row: DbNetsessionTourneyDiscordDmOutbox,
    reason: str,
    now: datetime,
) -> None:
    if db_row.attempt_count >= DISCORD_DM_MAX_ATTEMPTS:
        _mark_discord_dm_outbox_dead_letter(
            db_row,
            f'Zustellung wiederholt fehlgeschlagen. Letzter Fehler: {reason}',
            now,
        )
        return

    backoff_minutes = 2 ** min(db_row.attempt_count, 6)
    db_row.status = DiscordDmOutboxStatus.failed.value
    db_row.next_attempt_at = now + timedelta(minutes=backoff_minutes)
    db_row.last_error = reason[:500]
    db_row.updated_at = now


def _send_discord_dm(
    *,
    application_id: str,
    bot_token: str,
    discord_user_id: str,
    payload: dict[str, Any],
) -> None:
    if not application_id.strip():
        raise ValueError('Discord Application ID fehlt.')

    headers = {
        'Authorization': f'Bot {bot_token}',
        'Content-Type': 'application/json',
        'User-Agent': f'BYCEPS Netsession/{application_id}',
    }

    with httpx.Client(
        base_url='https://discord.com/api/v10',
        timeout=DISCORD_DM_TIMEOUT_SECONDS,
        headers=headers,
    ) as client:
        dm_response = client.post(
            '/users/@me/channels',
            json={'recipient_id': discord_user_id},
        )
        dm_response.raise_for_status()
        channel_id = str(dm_response.json().get('id') or '').strip()
        if not channel_id:
            raise ValueError('Discord-DM-Kanal konnte nicht erstellt werden.')

        message_response = client.post(
            f'/channels/{channel_id}/messages',
            json=payload,
        )
        message_response.raise_for_status()

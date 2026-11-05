"""
byceps.services.netsession_tourney.discord_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Discord forum integration: configuration, event queue and its processing.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
import structlog

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyDiscordOutbox,
    DbNetsessionTourneyTournament,
)
from .discord_dm_service import (
    DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS,
    get_configured_discord_bot_credentials,
)
from .discord_forum_api import (
    _post_discord_forum_message,
)
from .discord_forum_threads import (
    _recover_deleted_discord_forum_thread,
    _sync_discord_thread_for_tournament,
)
from .discord_payloads import (
    _build_discord_message_payload,
)
from .models import (
    DiscordOutboxID,
    DiscordOutboxStatus,
    Tournament,
    TournamentID,
)
from .service_helpers import (
    _append_audit_log,
    _db_tournament_to_model,
)
from .tournament_queries import (
    _find_db_tournament_for_party,
)


log = structlog.get_logger()


DISCORD_SUPPORTED_EVENTS = {
    'manual_announcement',
    'match_completed',
    'stage_started',
    'tournament_canceled',
    'tournament_finished',
    'tournament_live',
}


DISCORD_MAX_ATTEMPTS = 5


def enqueue_discord_event(
    party_id: PartyID,
    tournament_id: TournamentID,
    *,
    event_name: str,
    payload: dict[str, Any],
) -> None:
    if event_name not in DISCORD_SUPPORTED_EVENTS:
        log.warning(
            'netsession_tourney.discord_event_ignored_unknown',
            tournament_id=str(tournament_id),
            event_name=event_name,
        )
        return

    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None or not db_tournament.discord_enabled:
        return

    if event_name not in (db_tournament.discord_event_mask or []):
        return

    db.session.add(
        DbNetsessionTourneyDiscordOutbox(
            DiscordOutboxID(generate_uuid7()),
            tournament_id,
            event_name,
            payload,
            datetime.utcnow(),
        )
    )
    db.session.commit()


def process_discord_outbox(*, limit: int = 50) -> int:
    now = datetime.utcnow()
    db_rows = _load_due_discord_outbox_rows(now, limit)

    match get_configured_discord_bot_credentials():
        case Err(message):
            credentials_error = message
            credentials = None
        case Ok(credentials):
            credentials_error = None

    for db_row in db_rows:
        db_row.attempt_count += 1
        db_row.updated_at = now
        _deliver_discord_outbox_row(db_row, credentials, credentials_error, now)

    db.session.commit()
    return len(db_rows)


def _load_due_discord_outbox_rows(now: datetime, limit: int):
    return db.session.scalars(
        select(DbNetsessionTourneyDiscordOutbox)
        .filter(
            DbNetsessionTourneyDiscordOutbox.status.in_(
                [
                    DiscordOutboxStatus.pending.value,
                    DiscordOutboxStatus.failed.value,
                ]
            )
        )
        .filter(
            (DbNetsessionTourneyDiscordOutbox.next_attempt_at.is_(None))
            | (DbNetsessionTourneyDiscordOutbox.next_attempt_at <= now)
        )
        .order_by(DbNetsessionTourneyDiscordOutbox.created_at.asc())
        .limit(limit)
    ).all()


def _deliver_discord_outbox_row(db_row, credentials, credentials_error, now) -> None:
    """Post one event to the tournament's forum thread, or schedule a retry
    (temporary problem) or give up (dead letter)."""
    db_tournament = db.session.get(DbNetsessionTourneyTournament, db_row.tournament_id)
    dead_letter_reason = _discord_dead_letter_reason(db_tournament)
    if dead_letter_reason is not None:
        _mark_discord_outbox_dead_letter(db_row, dead_letter_reason, now)
        return

    if credentials is None:
        _schedule_discord_outbox_retry(
            db_row,
            credentials_error or 'Keine gültige Discord-Bot-Konfiguration aktiv.',
            now,
        )
        return

    if not db_tournament.discord_thread_id:
        try:
            _sync_discord_thread_for_tournament(db_tournament)
        except Exception:
            pass

    thread_id = db_tournament.discord_thread_id
    if not thread_id:
        _schedule_discord_outbox_retry(
            db_row, 'Discord-Forum-Thread konnte noch nicht erstellt werden.', now
        )
        return

    application_id, bot_token = credentials

    def post(to_thread_id) -> None:
        _post_discord_forum_message(
            application_id=application_id,
            bot_token=bot_token,
            thread_id=to_thread_id,
            payload=_build_discord_message_payload(db_tournament, db_row),
        )

    try:
        post(thread_id)
    except httpx.HTTPStatusError as exc:
        recovered_thread_id = _recover_deleted_discord_forum_thread(
            db_tournament=db_tournament, failed_thread_id=thread_id, exc=exc
        )
        if not recovered_thread_id:
            _retry_after_discord_error(db_row, exc, now)
            return
        try:
            post(recovered_thread_id)
        except httpx.HTTPError as retry_exc:
            _retry_after_discord_error(db_row, retry_exc, now)
            return
    except httpx.HTTPError as exc:
        _retry_after_discord_error(db_row, exc, now)
        return

    db_row.status = DiscordOutboxStatus.sent.value
    db_row.next_attempt_at = None
    db_row.last_error = None


def _discord_dead_letter_reason(db_tournament) -> str | None:
    if db_tournament is None:
        return 'Unknown tournament for Discord outbox item.'
    if not db_tournament.discord_enabled:
        return 'Discord-Forum ist für dieses Turnier nicht aktiviert.'
    if not db_tournament.discord_forum_channel_id:
        return 'Keine Discord-Forum-Channel-ID konfiguriert.'
    return None


def _retry_after_discord_error(db_row, exc: Exception, now: datetime) -> None:
    _schedule_discord_outbox_retry(
        db_row, f'Discord-Forum-Anfrage fehlgeschlagen: {type(exc).__name__}', now
    )
    log.warning(
        'netsession_tourney.discord_forum_delivery_failed',
        tournament_id=str(db_row.tournament_id),
        outbox_id=str(db_row.id),
        event_name=db_row.event_name,
        error=type(exc).__name__,
    )


def configure_discord(
    party_id: PartyID,
    tournament_id: TournamentID,
    initiator: User,
    *,
    enabled: bool,
    forum_channel_id: str | None,
    discord_forum_image_url: str | None,
    applied_tag_ids: list[str],
    event_mask: list[str],
    discord_dm_enabled: bool,
    discord_dm_event_mask: list[str],
) -> Result[Tournament, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    normalized_forum_channel_id = (forum_channel_id or '').strip() or None
    normalized_discord_forum_image_url = (
        discord_forum_image_url.strip() if discord_forum_image_url else None
    )
    normalized_event_mask = sorted(set(event_mask))
    if enabled and not normalized_forum_channel_id:
        return Err('Eine Discord-Forum-Channel-ID ist erforderlich.')

    invalid_events = sorted(
        set(normalized_event_mask).difference(DISCORD_SUPPORTED_EVENTS)
    )
    if invalid_events:
        return Err(
            'Unbekannte Discord-Forum-Events: ' + ', '.join(invalid_events)
        )
    if enabled and not normalized_event_mask:
        return Err(
            'Mindestens ein Discord-Forum-Event muss ausgewählt werden.'
        )

    invalid_dm_events = sorted(
        set(discord_dm_event_mask).difference(DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS)
    )
    if invalid_dm_events:
        return Err(
            'Unbekannte Discord-DM-Ereignisse: ' + ', '.join(invalid_dm_events)
        )

    normalized_discord_dm_event_mask = sorted(set(discord_dm_event_mask))
    if discord_dm_enabled and not normalized_discord_dm_event_mask:
        return Err(
            'Mindestens ein Discord-DM-Event muss ausgewählt werden.'
        )

    forum_channel_changed = (
        db_tournament.discord_forum_channel_id != normalized_forum_channel_id
    )
    db_tournament.discord_enabled = enabled
    db_tournament.discord_forum_channel_id = normalized_forum_channel_id
    db_tournament.discord_forum_image_url = normalized_discord_forum_image_url
    if forum_channel_changed:
        db_tournament.discord_thread_id = None
    db_tournament.discord_applied_tag_ids = list(applied_tag_ids)
    db_tournament.discord_event_mask = normalized_event_mask
    db_tournament.discord_dm_enabled = discord_dm_enabled
    db_tournament.discord_dm_event_mask = normalized_discord_dm_event_mask
    db_tournament.updated_at = datetime.utcnow()

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='tournament',
        object_id=tournament_id,
        action='discord_configuration_updated',
        payload={
            'enabled': enabled,
            'forum_channel_id': normalized_forum_channel_id,
            'discord_forum_image_url': normalized_discord_forum_image_url,
            'event_mask': normalized_event_mask,
            'discord_dm_enabled': discord_dm_enabled,
            'discord_dm_event_mask': normalized_discord_dm_event_mask,
        },
        created_at=datetime.utcnow(),
    )

    db.session.commit()
    if db_tournament.discord_enabled:
        _sync_discord_thread_for_tournament(db_tournament)

    return Ok(_db_tournament_to_model(db_tournament))


def _mark_discord_outbox_dead_letter(
    db_row: DbNetsessionTourneyDiscordOutbox,
    reason: str,
    now: datetime,
) -> None:
    db_row.status = DiscordOutboxStatus.dead_letter.value
    db_row.next_attempt_at = None
    db_row.last_error = reason[:500]
    db_row.updated_at = now


def _schedule_discord_outbox_retry(
    db_row: DbNetsessionTourneyDiscordOutbox,
    reason: str,
    now: datetime,
) -> None:
    if db_row.attempt_count >= DISCORD_MAX_ATTEMPTS:
        _mark_discord_outbox_dead_letter(
            db_row,
            f'Delivery failed repeatedly. Last error: {reason}',
            now,
        )
        return

    backoff_minutes = 2 ** min(db_row.attempt_count, 6)
    db_row.status = DiscordOutboxStatus.failed.value
    db_row.next_attempt_at = now + timedelta(minutes=backoff_minutes)
    db_row.last_error = reason[:500]
    db_row.updated_at = now

"""
byceps.services.netsession_tourney.discord_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Discord forum integration: configuration, event queue and its processing.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
import structlog

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyDiscordOutbox,
    DbNetsessionTourneyTournament,
)
from .discord_dm_service import (
    get_configured_discord_bot_credentials,
)
from .discord_forum_api import (
    post_discord_forum_message,
)
from .discord_forum_threads import (
    recover_deleted_discord_forum_thread,
    sync_discord_thread_for_tournament,
)
from .discord_payloads import (
    build_discord_message_payload,
)
from .discord_service_configuration import (
    configure_discord as configure_discord,
)
from .discord_service_validation import (
    DISCORD_SUPPORTED_EVENTS,
)
from .models import (
    DiscordOutboxID,
    DiscordOutboxStatus,
    TournamentID,
)
from .outbox_processing import process_outbox_rows
from .tournament_queries import (
    find_db_tournament_for_party,
)


log = structlog.get_logger()


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

    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
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


def process_discord_outbox(*, limit: int = 50) -> int:
    now = datetime.utcnow()
    db_rows = _load_due_discord_outbox_rows(now, limit)

    match get_configured_discord_bot_credentials():
        case Err(message):
            credentials_error = message
            credentials = None
        case Ok(credentials):
            credentials_error = None

    process_outbox_rows(
        db_rows,
        lambda db_row, now: _deliver_discord_outbox_row(
            db_row, credentials, credentials_error, now
        ),
        _mark_discord_outbox_dead_letter,
        now,
        outbox_name='discord',
    )
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


def _deliver_discord_outbox_row(
    db_row, credentials, credentials_error, now
) -> None:
    """Post one event to the tournament's forum thread, or schedule a retry
    (temporary problem) or give up (dead letter)."""
    db_tournament = db.session.get(
        DbNetsessionTourneyTournament, db_row.tournament_id
    )
    dead_letter_reason = _discord_dead_letter_reason(db_tournament)
    if dead_letter_reason is not None:
        _mark_discord_outbox_dead_letter(db_row, dead_letter_reason, now)
        return

    if credentials is None:
        _schedule_discord_outbox_retry(
            db_row,
            credentials_error
            or 'Keine gültige Discord-Bot-Konfiguration aktiv.',
            now,
        )
        return

    thread_id = _ensure_discord_thread_id(db_tournament)
    if not thread_id:
        _schedule_discord_outbox_retry(
            db_row,
            'Discord-Forum-Thread konnte noch nicht erstellt werden.',
            now,
        )
        return

    if not _post_discord_outbox_row(
        db_row, db_tournament, credentials, thread_id, now
    ):
        return

    db_row.status = DiscordOutboxStatus.sent.value
    db_row.next_attempt_at = None
    db_row.last_error = None


def _ensure_discord_thread_id(db_tournament) -> str | None:
    """Create the tournament's forum thread if it has none yet, and return
    its ID (`None` if it still has none)."""
    if not db_tournament.discord_thread_id:
        try:
            sync_discord_thread_for_tournament(db_tournament)
        except Exception as exc:
            # Not fatal: without a thread, the delivery is retried below.
            log.warning(
                'netsession_tourney.discord_thread_sync_failed',
                tournament_id=str(db_tournament.id),
                error=type(exc).__name__,
            )

    return db_tournament.discord_thread_id


def _post_discord_outbox_row(
    db_row, db_tournament, credentials, thread_id, now: datetime
) -> bool:
    """Post the row's message to the thread (to a recreated one if the
    thread was deleted). Return `False` if a retry has been scheduled."""
    application_id, bot_token = credentials

    def post(to_thread_id) -> None:
        post_discord_forum_message(
            application_id=application_id,
            bot_token=bot_token,
            thread_id=to_thread_id,
            payload=build_discord_message_payload(db_tournament, db_row),
        )

    try:
        post(thread_id)
    except httpx.HTTPStatusError as exc:
        return _repost_to_recovered_discord_thread(
            db_row, db_tournament, thread_id, exc, post, now
        )
    except httpx.HTTPError as exc:
        _retry_after_discord_error(db_row, exc, now)
        return False

    return True


def _repost_to_recovered_discord_thread(
    db_row,
    db_tournament,
    thread_id,
    exc: httpx.HTTPStatusError,
    post: Callable[[Any], None],
    now: datetime,
) -> bool:
    recovered_thread_id = recover_deleted_discord_forum_thread(
        db_tournament=db_tournament, failed_thread_id=thread_id, exc=exc
    )
    if not recovered_thread_id:
        _retry_after_discord_error(db_row, exc, now)
        return False
    try:
        post(recovered_thread_id)
    except httpx.HTTPError as retry_exc:
        _retry_after_discord_error(db_row, retry_exc, now)
        return False

    return True


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
        db_row,
        f'Discord-Forum-Anfrage fehlgeschlagen: {type(exc).__name__}',
        now,
    )
    log.warning(
        'netsession_tourney.discord_forum_delivery_failed',
        tournament_id=str(db_row.tournament_id),
        outbox_id=str(db_row.id),
        event_name=db_row.event_name,
        error=type(exc).__name__,
    )


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

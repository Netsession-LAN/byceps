"""
byceps.services.netsession_tourney.discord_forum_threads
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

One Discord forum thread per tournament: create, update, recover.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import structlog

from byceps.database import db
from byceps.util.result import Err, Ok

from .dbmodels import (
    DbNetsessionTourneyTournament,
)
from .discord_dm_service import (
    get_configured_discord_bot_credentials,
)
from .discord_forum_api import (
    create_discord_forum_thread,
    get_discord_channel,
    is_discord_resource_missing,
    patch_discord_channel,
)
from .discord_forum_threads_parts import (
    _clear_discord_thread_reference,
    _patch_discord_thread_starter_message,
)
from .discord_payloads import (
    build_discord_forum_thread_payload,
)
from .service_helpers import (
    append_audit_log,
)


log = structlog.get_logger()


def _ensure_discord_thread_for_tournament(
    db_tournament: DbNetsessionTourneyTournament,
) -> None:
    sync_discord_thread_for_tournament(db_tournament, update_existing=False)


def sync_discord_thread_for_tournament(
    db_tournament: DbNetsessionTourneyTournament,
    *,
    update_existing: bool = True,
) -> None:
    credentials = _get_discord_thread_bot_credentials(db_tournament)
    if credentials is None:
        return

    application_id, bot_token = credentials

    if (
        db_tournament.discord_thread_id
        and not _validate_existing_discord_thread(
            db_tournament, application_id=application_id, bot_token=bot_token
        )
    ):
        return

    if db_tournament.discord_thread_id:
        _sync_existing_discord_thread(
            db_tournament,
            update_existing=update_existing,
            application_id=application_id,
            bot_token=bot_token,
        )
        return

    _create_discord_thread_for_tournament(
        db_tournament, application_id=application_id, bot_token=bot_token
    )


def _get_discord_thread_bot_credentials(
    db_tournament: DbNetsessionTourneyTournament,
) -> tuple[str, str] | None:
    """Return the bot's application ID and token, or `None` if the
    tournament has no Discord forum or the bot is not (validly)
    configured."""
    if (
        not db_tournament.discord_enabled
        or not db_tournament.discord_forum_channel_id
    ):
        return None

    match get_configured_discord_bot_credentials():
        case Err(message):
            log.warning(
                'netsession_tourney.discord_forum_thread_credentials_invalid',
                tournament_id=str(db_tournament.id),
                error=message,
            )
            return None
        case Ok(None):
            return None
        case Ok((application_id, bot_token)):
            return application_id, bot_token


def _sync_existing_discord_thread(
    db_tournament: DbNetsessionTourneyTournament,
    *,
    update_existing: bool,
    application_id: str,
    bot_token: str,
) -> None:
    if not update_existing:
        return

    try:
        _update_discord_forum_thread(
            db_tournament=db_tournament,
            application_id=application_id,
            bot_token=bot_token,
        )
    except httpx.HTTPError as exc:
        log.warning(
            'netsession_tourney.discord_forum_thread_sync_failed',
            tournament_id=str(db_tournament.id),
            thread_id=str(db_tournament.discord_thread_id),
            error=type(exc).__name__,
        )


def _validate_existing_discord_thread(
    db_tournament: DbNetsessionTourneyTournament,
    *,
    application_id: str,
    bot_token: str,
) -> bool:
    """Check that the referenced thread still exists; clear the reference
    if it is gone. Return `False` if syncing must stop (unclear state)."""
    try:
        get_discord_channel(
            application_id=application_id,
            bot_token=bot_token,
            channel_id=db_tournament.discord_thread_id,
        )
    except httpx.HTTPStatusError as exc:
        if is_discord_resource_missing(exc):
            _clear_discord_thread_reference(
                db_tournament,
                audit_action='discord_thread_missing_reset',
                audit_payload={
                    'thread_id': db_tournament.discord_thread_id,
                    'reason': 'thread_missing',
                },
            )
        else:
            log.warning(
                'netsession_tourney.discord_forum_thread_validate_failed',
                tournament_id=str(db_tournament.id),
                thread_id=str(db_tournament.discord_thread_id),
                error=type(exc).__name__,
            )
            return False
    except httpx.HTTPError as exc:
        log.warning(
            'netsession_tourney.discord_forum_thread_validate_failed',
            tournament_id=str(db_tournament.id),
            thread_id=str(db_tournament.discord_thread_id),
            error=type(exc).__name__,
        )
        return False

    return True


def _create_discord_thread_for_tournament(
    db_tournament: DbNetsessionTourneyTournament,
    *,
    application_id: str,
    bot_token: str,
) -> None:
    payload = build_discord_forum_thread_payload(db_tournament)

    try:
        thread_id = create_discord_forum_thread(
            application_id=application_id,
            bot_token=bot_token,
            forum_channel_id=db_tournament.discord_forum_channel_id,
            payload=payload,
        )
    except (httpx.HTTPError, ValueError) as exc:
        log.warning(
            'netsession_tourney.discord_forum_thread_create_failed',
            tournament_id=str(db_tournament.id),
            error=type(exc).__name__,
        )
        return

    db_tournament.discord_thread_id = thread_id
    db_tournament.updated_at = datetime.utcnow()

    append_audit_log(
        actor_user_id=None,
        object_type='tournament',
        object_id=db_tournament.id,
        action='discord_thread_created',
        payload={'thread_id': thread_id},
        created_at=datetime.utcnow(),
    )
    db.session.commit()


def _update_discord_forum_thread(
    *,
    db_tournament: DbNetsessionTourneyTournament,
    application_id: str,
    bot_token: str,
) -> None:
    thread_id = db_tournament.discord_thread_id
    if not thread_id:
        return

    payload = build_discord_forum_thread_payload(db_tournament)

    if not _patch_discord_thread_channel(
        db_tournament,
        thread_id=thread_id,
        payload=payload,
        application_id=application_id,
        bot_token=bot_token,
    ):
        return

    _patch_discord_thread_starter_message(
        thread_id=thread_id,
        payload=payload,
        application_id=application_id,
        bot_token=bot_token,
    )


def _patch_discord_thread_channel(
    db_tournament: DbNetsessionTourneyTournament,
    *,
    thread_id: str,
    payload: dict[str, Any],
    application_id: str,
    bot_token: str,
) -> bool:
    """Update the thread's name and tags. Return `False` if the thread was
    gone and has been recreated instead."""
    channel_payload: dict[str, Any] = {'name': payload['name']}
    if 'applied_tags' in payload:
        channel_payload['applied_tags'] = payload['applied_tags']

    try:
        patch_discord_channel(
            application_id=application_id,
            bot_token=bot_token,
            channel_id=thread_id,
            payload=channel_payload,
        )
    except httpx.HTTPStatusError as exc:
        if is_discord_resource_missing(exc):
            _clear_discord_thread_reference(
                db_tournament,
                audit_action='discord_thread_missing_reset',
                audit_payload={
                    'thread_id': thread_id,
                    'reason': 'thread_missing_while_updating',
                },
            )
            sync_discord_thread_for_tournament(
                db_tournament, update_existing=False
            )
            return False
        raise

    return True


def recover_deleted_discord_forum_thread(
    *,
    db_tournament: DbNetsessionTourneyTournament,
    failed_thread_id: str,
    exc: httpx.HTTPStatusError,
) -> str | None:
    if not is_discord_resource_missing(exc):
        return None

    if db_tournament.discord_thread_id == failed_thread_id:
        _clear_discord_thread_reference(
            db_tournament,
            audit_action='discord_thread_missing_reset',
            audit_payload={
                'thread_id': failed_thread_id,
                'reason': 'message_delivery_failed_missing_thread',
            },
        )

    try:
        sync_discord_thread_for_tournament(db_tournament, update_existing=False)
    except httpx.HTTPError:
        return None

    return db_tournament.discord_thread_id

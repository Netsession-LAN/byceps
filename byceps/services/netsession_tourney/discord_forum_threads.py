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
    _create_discord_forum_thread,
    _get_discord_channel,
    _is_discord_resource_missing,
    _patch_discord_channel,
    _patch_discord_forum_starter_message,
)
from .discord_payloads import (
    _build_discord_forum_thread_payload,
)
from .service_helpers import (
    _append_audit_log,
)


log = structlog.get_logger()


def _ensure_discord_thread_for_tournament(
    db_tournament: DbNetsessionTourneyTournament,
) -> None:
    _sync_discord_thread_for_tournament(db_tournament, update_existing=False)


def _sync_discord_thread_for_tournament(
    db_tournament: DbNetsessionTourneyTournament,
    *,
    update_existing: bool = True,
) -> None:
    if not db_tournament.discord_enabled or not db_tournament.discord_forum_channel_id:
        return

    match get_configured_discord_bot_credentials():
        case Err(message):
            log.warning(
                'netsession_tourney.discord_forum_thread_credentials_invalid',
                tournament_id=str(db_tournament.id),
                error=message,
            )
            return
        case Ok(None):
            return
        case Ok((application_id, bot_token)):
            pass

    if db_tournament.discord_thread_id:
        if not _validate_existing_discord_thread(
            db_tournament, application_id=application_id, bot_token=bot_token
        ):
            return

    if db_tournament.discord_thread_id:
        if update_existing:
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
        return

    _create_discord_thread_for_tournament(
        db_tournament, application_id=application_id, bot_token=bot_token
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
        _get_discord_channel(
            application_id=application_id,
            bot_token=bot_token,
            channel_id=db_tournament.discord_thread_id,
        )
    except httpx.HTTPStatusError as exc:
        if _is_discord_resource_missing(exc):
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
    payload = _build_discord_forum_thread_payload(db_tournament)

    try:
        thread_id = _create_discord_forum_thread(
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

    _append_audit_log(
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

    payload = _build_discord_forum_thread_payload(db_tournament)
    channel_payload: dict[str, Any] = {'name': payload['name']}
    if 'applied_tags' in payload:
        channel_payload['applied_tags'] = payload['applied_tags']

    try:
        _patch_discord_channel(
            application_id=application_id,
            bot_token=bot_token,
            channel_id=thread_id,
            payload=channel_payload,
        )
    except httpx.HTTPStatusError as exc:
        if _is_discord_resource_missing(exc):
            _clear_discord_thread_reference(
                db_tournament,
                audit_action='discord_thread_missing_reset',
                audit_payload={
                    'thread_id': thread_id,
                    'reason': 'thread_missing_while_updating',
                },
            )
            _sync_discord_thread_for_tournament(
                db_tournament, update_existing=False
            )
            return
        raise

    try:
        _patch_discord_forum_starter_message(
            application_id=application_id,
            bot_token=bot_token,
            thread_id=thread_id,
            payload=payload['message'],
        )
    except httpx.HTTPStatusError as exc:
        if not _is_discord_resource_missing(exc):
            raise
    except httpx.HTTPError:
        return


def _recover_deleted_discord_forum_thread(
    *,
    db_tournament: DbNetsessionTourneyTournament,
    failed_thread_id: str,
    exc: httpx.HTTPStatusError,
) -> str | None:
    if not _is_discord_resource_missing(exc):
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
        _sync_discord_thread_for_tournament(
            db_tournament, update_existing=False
        )
    except httpx.HTTPError:
        return None

    return db_tournament.discord_thread_id


def _clear_discord_thread_reference(
    db_tournament: DbNetsessionTourneyTournament,
    *,
    audit_action: str,
    audit_payload: dict[str, Any],
) -> None:
    if not db_tournament.discord_thread_id:
        return

    db_tournament.discord_thread_id = None
    db_tournament.updated_at = datetime.utcnow()

    _append_audit_log(
        actor_user_id=None,
        object_type='tournament',
        object_id=db_tournament.id,
        action=audit_action,
        payload=audit_payload,
        created_at=datetime.utcnow(),
    )
    db.session.commit()

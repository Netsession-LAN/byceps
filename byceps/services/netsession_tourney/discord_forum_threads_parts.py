"""
byceps.services.netsession_tourney.discord_forum_threads_parts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Parts of the tournament forum thread handling: patching the starter
message and clearing a lost thread reference.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from byceps.database import db

from .dbmodels import (
    DbNetsessionTourneyTournament,
)
from .discord_forum_api import (
    is_discord_resource_missing,
    patch_discord_forum_starter_message,
)
from .service_helpers import (
    append_audit_log,
)


def _patch_discord_thread_starter_message(
    *,
    thread_id: str,
    payload: dict[str, Any],
    application_id: str,
    bot_token: str,
) -> None:
    try:
        patch_discord_forum_starter_message(
            application_id=application_id,
            bot_token=bot_token,
            thread_id=thread_id,
            payload=payload['message'],
        )
    except httpx.HTTPStatusError as exc:
        if not is_discord_resource_missing(exc):
            raise
    except httpx.HTTPError:
        return


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

    append_audit_log(
        actor_user_id=None,
        object_type='tournament',
        object_id=db_tournament.id,
        action=audit_action,
        payload=audit_payload,
        created_at=datetime.utcnow(),
    )
    db.session.commit()

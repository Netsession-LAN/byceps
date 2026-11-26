"""
byceps.services.netsession_tourney.discord_service_configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Configuration of the Discord integration per party.
"""

from __future__ import annotations

from datetime import datetime

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result

from .discord_forum_threads import (
    sync_discord_thread_for_tournament,
)
from .discord_service_validation import (
    validate_discord_applied_tag_ids,
    validate_discord_configuration,
)
from .models import (
    Tournament,
    TournamentID,
)
from .service_helpers import (
    append_audit_log,
    db_tournament_to_model,
)
from .tournament_queries import (
    find_db_tournament_for_party,
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
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    normalized_forum_channel_id = _normalize_discord_forum_channel_id(
        forum_channel_id
    )
    normalized_discord_forum_image_url = _normalize_discord_forum_image_url(
        discord_forum_image_url
    )
    normalized_event_mask = sorted(set(event_mask))
    error = validate_discord_configuration(
        enabled=enabled,
        normalized_forum_channel_id=normalized_forum_channel_id,
        normalized_event_mask=normalized_event_mask,
        discord_dm_enabled=discord_dm_enabled,
        discord_dm_event_mask=discord_dm_event_mask,
    ) or validate_discord_applied_tag_ids(applied_tag_ids)
    if error is not None:
        return Err(error)

    normalized_discord_dm_event_mask = sorted(set(discord_dm_event_mask))

    _apply_discord_configuration(
        db_tournament,
        enabled=enabled,
        forum_channel_id=normalized_forum_channel_id,
        discord_forum_image_url=normalized_discord_forum_image_url,
        applied_tag_ids=applied_tag_ids,
        event_mask=normalized_event_mask,
        discord_dm_enabled=discord_dm_enabled,
        discord_dm_event_mask=normalized_discord_dm_event_mask,
    )

    append_audit_log(
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
        sync_discord_thread_for_tournament(db_tournament)

    return Ok(db_tournament_to_model(db_tournament))


def _normalize_discord_forum_channel_id(
    forum_channel_id: str | None,
) -> str | None:
    return (forum_channel_id or '').strip() or None


def _normalize_discord_forum_image_url(
    discord_forum_image_url: str | None,
) -> str | None:
    return discord_forum_image_url.strip() if discord_forum_image_url else None


def _apply_discord_configuration(
    db_tournament,
    *,
    enabled: bool,
    forum_channel_id: str | None,
    discord_forum_image_url: str | None,
    applied_tag_ids: list[str],
    event_mask: list[str],
    discord_dm_enabled: bool,
    discord_dm_event_mask: list[str],
) -> None:
    forum_channel_changed = (
        db_tournament.discord_forum_channel_id != forum_channel_id
    )
    db_tournament.discord_enabled = enabled
    db_tournament.discord_forum_channel_id = forum_channel_id
    db_tournament.discord_forum_image_url = discord_forum_image_url
    if forum_channel_changed:
        db_tournament.discord_thread_id = None
    db_tournament.discord_applied_tag_ids = list(applied_tag_ids)
    db_tournament.discord_event_mask = event_mask
    db_tournament.discord_dm_enabled = discord_dm_enabled
    db_tournament.discord_dm_event_mask = discord_dm_event_mask
    db_tournament.updated_at = datetime.utcnow()

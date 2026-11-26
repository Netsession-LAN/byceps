"""
byceps.services.netsession_tourney.discord_service_validation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Validation of a tournament's Discord configuration.
"""

from __future__ import annotations

from .discord_dm_service import (
    DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS,
)
from .discord_ids import is_discord_id


DISCORD_SUPPORTED_EVENTS = {
    'manual_announcement',
    'match_completed',
    'stage_started',
    'tournament_canceled',
    'tournament_finished',
    'tournament_live',
}


def validate_discord_configuration(
    *,
    enabled: bool,
    normalized_forum_channel_id: str | None,
    normalized_event_mask: list[str],
    discord_dm_enabled: bool,
    discord_dm_event_mask: list[str],
) -> str | None:
    """Return the first validation error message, or `None` if valid."""
    return (
        _validate_discord_forum_channel_id(enabled, normalized_forum_channel_id)
        or _validate_discord_forum_event_mask(enabled, normalized_event_mask)
        or _validate_discord_dm_event_mask(
            discord_dm_enabled, discord_dm_event_mask
        )
    )


def _validate_discord_forum_channel_id(
    enabled: bool, normalized_forum_channel_id: str | None
) -> str | None:
    if enabled and not normalized_forum_channel_id:
        return 'Eine Discord-Forum-Channel-ID ist erforderlich.'
    if normalized_forum_channel_id and not is_discord_id(
        normalized_forum_channel_id
    ):
        return (
            'Die Discord-Forum-Channel-ID muss aus 17 bis 20 Ziffern bestehen.'
        )
    return None


def _validate_discord_forum_event_mask(
    enabled: bool, normalized_event_mask: list[str]
) -> str | None:
    invalid_events = sorted(
        set(normalized_event_mask).difference(DISCORD_SUPPORTED_EVENTS)
    )
    if invalid_events:
        return 'Unbekannte Discord-Forum-Events: ' + ', '.join(invalid_events)
    if enabled and not normalized_event_mask:
        return 'Mindestens ein Discord-Forum-Event muss ausgewählt werden.'
    return None


def _validate_discord_dm_event_mask(
    discord_dm_enabled: bool, discord_dm_event_mask: list[str]
) -> str | None:
    invalid_dm_events = sorted(
        set(discord_dm_event_mask).difference(
            DISCORD_DM_SUPPORTED_NOTIFICATION_KINDS
        )
    )
    if invalid_dm_events:
        return 'Unbekannte Discord-DM-Ereignisse: ' + ', '.join(
            invalid_dm_events
        )

    normalized_discord_dm_event_mask = sorted(set(discord_dm_event_mask))
    if discord_dm_enabled and not normalized_discord_dm_event_mask:
        return 'Mindestens ein Discord-DM-Event muss ausgewählt werden.'

    return None


def validate_discord_applied_tag_ids(applied_tag_ids: list[str]) -> str | None:
    if not all(is_discord_id(t) for t in applied_tag_ids):
        return 'Discord-Tag-IDs müssen aus 17 bis 20 Ziffern bestehen.'
    return None

"""
byceps.services.netsession_tourney.discord_parts_dm_embed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Building blocks for the embed of a Discord direct message about a
tournament notification: event metadata, image URLs and embed fields.
"""

from __future__ import annotations

from typing import Any

from .dbmodels import DbNetsessionTourneyTournament
from .notification_urls import (
    build_absolute_notification_url,
    build_browser_push_logo_urls,
)
from .tournament_queries import (
    build_flatout2_round_race_lines,
)


DISCORD_DM_EVENT_META_BY_KIND: dict[str, dict[str, str]] = {
    'tournament_live': {
        'emoji': '🟢',
        'label': 'Turnier live',
        'headline': 'Turnier ist jetzt live',
    },
    'tournament_canceled': {
        'emoji': '⛔',
        'label': 'Turnier abgesagt',
        'headline': 'Turnier wurde abgesagt',
    },
    'checkin_open': {
        'emoji': '✅',
        'label': 'Check-in offen',
        'headline': 'Der Check-in ist offen – jetzt einchecken',
    },
    'match_ready': {
        'emoji': '🎮',
        'label': 'Match spielbereit',
        'headline': 'Match ist spielbereit',
    },
    'flatout2_host_assigned': {
        'emoji': '🏁',
        'label': 'Host ausgewählt',
        'headline': 'Du bist Host für das nächste Rennen',
    },
    'result_submitted': {
        'emoji': '📝',
        'label': 'Ergebnis übermittelt',
        'headline': 'Ergebnis wurde übermittelt',
    },
}


DISCORD_DM_DEFAULT_EVENT_META: dict[str, str] = {
    'emoji': '🔔',
    'label': 'Benachrichtigung',
    'headline': 'Neues Update',
}


def build_discord_dm_image_urls(
    db_tournament: DbNetsessionTourneyTournament,
) -> tuple[str | None, str | None]:
    """Return the absolute brand icon URL and thumbnail URL (if any)."""
    icon_url, _image_url = build_browser_push_logo_urls(db_tournament)
    brand_icon_url = (
        build_absolute_notification_url(db_tournament.party_id, icon_url)
        if icon_url
        else None
    )
    thumbnail_source_url = db_tournament.logo_url or icon_url
    thumbnail_url = (
        build_absolute_notification_url(
            db_tournament.party_id, thumbnail_source_url
        )
        if thumbnail_source_url
        else None
    )
    return brand_icon_url, thumbnail_url


def build_discord_dm_embed_fields(
    db_tournament: DbNetsessionTourneyTournament,
    *,
    event_meta: dict[str, str],
    kind: str,
    payload: dict[str, Any],
    match_label: str | None,
    url: str | None,
) -> list[dict[str, Any]]:
    fields = [
        {
            'name': 'Ereignis',
            'value': str(event_meta['label'])[:1024],
            'inline': True,
        },
        {
            'name': 'Turnier',
            'value': db_tournament.title[:1024],
            'inline': True,
        },
    ]

    if match_label:
        fields.append(
            {
                'name': 'Spiel',
                'value': match_label[:1024],
                'inline': True,
            }
        )

    if kind == 'flatout2_host_assigned':
        fields.extend(_build_flatout2_host_assigned_fields(payload))

    if url:
        fields.append(
            {
                'name': 'Oeffnen',
                'value': f'[Direkt zur Seite]({url})',
                'inline': False,
            }
        )

    return fields


def _build_flatout2_host_assigned_fields(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    fields = []
    round_no = payload.get('round_no')
    if round_no:
        fields.append(
            {
                'name': 'Runde',
                'value': str(round_no)[:1024],
                'inline': True,
            }
        )
    race_lines = build_flatout2_round_race_lines(payload)
    if race_lines:
        fields.append(
            {
                'name': 'Rennen-Setup',
                'value': '\n'.join(race_lines)[:1024],
                'inline': False,
            }
        )
    return fields

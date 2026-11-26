"""
byceps.services.netsession_tourney.discord_dm_payloads
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Message payloads for Discord direct messages (outbox and test message).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from byceps.services.party.models import PartyID

from .browser_push_outbox_message import (
    build_browser_push_match_label,
    build_browser_push_message_payload,
)
from .dbmodels import (
    DbNetsessionTourneyNotification,
    DbNetsessionTourneyTournament,
)
from .discord_parts_dm_embed import (
    build_discord_dm_embed_fields,
    build_discord_dm_image_urls,
    DISCORD_DM_DEFAULT_EVENT_META,
    DISCORD_DM_EVENT_META_BY_KIND,
)
from .notification_urls import (
    build_absolute_notification_url,
)


def _build_discord_dm_message_payload(
    db_tournament: DbNetsessionTourneyTournament,
    db_notification: DbNetsessionTourneyNotification,
) -> dict[str, Any]:
    browser_payload = build_browser_push_message_payload(
        db_tournament, db_notification
    )
    payload = dict(db_notification.payload_json or {})
    kind = db_notification.kind
    match_label = build_browser_push_match_label(payload)
    body = _extract_discord_dm_body(browser_payload)
    url = build_absolute_notification_url(
        db_tournament.party_id,
        str(browser_payload.get('url') or f'/ns-tourneys/{db_tournament.slug}'),
    )
    brand_icon_url, thumbnail_url = build_discord_dm_image_urls(db_tournament)

    event_meta = DISCORD_DM_EVENT_META_BY_KIND.get(
        kind, DISCORD_DM_DEFAULT_EVENT_META
    )

    description_lines = [f'**{db_tournament.title}**', body]
    fields = build_discord_dm_embed_fields(
        db_tournament,
        event_meta=event_meta,
        kind=kind,
        payload=payload,
        match_label=match_label,
        url=url,
    )

    embed: dict[str, Any] = {
        'author': {'name': 'Netsession Turniere'},
        'title': f'{event_meta["emoji"]} {event_meta["headline"]}'[:256],
        'description': '\n'.join(description_lines)[:4096],
        'color': 0xFF2B00,
        'fields': fields,
        'footer': {'text': 'Netsession Turniere'},
        'timestamp': db_notification.created_at.replace(
            microsecond=0
        ).isoformat()
        + 'Z',
    }

    _apply_discord_dm_embed_links(embed, url, brand_icon_url, thumbnail_url)

    return {
        'allowed_mentions': {'parse': []},
        'embeds': [embed],
    }


def _extract_discord_dm_body(browser_payload: dict[str, Any]) -> str:
    return (
        str(browser_payload.get('body') or '').strip()
        or 'Es gibt ein neues Update.'
    )


def _apply_discord_dm_embed_links(
    embed: dict[str, Any],
    url: str | None,
    brand_icon_url: str | None,
    thumbnail_url: str | None,
) -> None:
    if url:
        embed['url'] = url

    if brand_icon_url:
        embed['author']['icon_url'] = brand_icon_url

    if thumbnail_url:
        embed['thumbnail'] = {'url': thumbnail_url}


def _build_test_discord_dm_message_payload(
    party_id: PartyID,
) -> dict[str, Any]:
    url = build_absolute_notification_url(party_id, '/ns-tourneys/')
    brand_icon_url = build_absolute_notification_url(
        party_id, '/static_sites/netsession/icon-192.png'
    )

    description_lines = [
        '**Counter-Strike 2 (5on5)**',
        'Upper Bracket • Spiel #2 ist jetzt spielbereit.',
        '',
        'So sehen künftige Turnier- und Match-Benachrichtigungen als Karte aus.',
    ]

    embed: dict[str, Any] = {
        'author': {'name': 'Netsession Turniere'},
        'title': '🧪 Discord-Testnachricht',
        'description': '\n'.join(description_lines)[:4096],
        'color': 0xFF2B00,
        'fields': [
            {
                'name': 'Ereignis',
                'value': 'Match spielbereit',
                'inline': True,
            },
            {
                'name': 'Turnier',
                'value': 'Counter-Strike 2 (5on5)',
                'inline': True,
            },
            {
                'name': 'Spiel',
                'value': 'WB #2',
                'inline': True,
            },
            {
                'name': 'Status',
                'value': 'Discord-DM-Zustellung aktiv',
                'inline': True,
            },
        ],
        'footer': {'text': 'Netsession Turniere'},
        'timestamp': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
    }

    if url:
        embed['url'] = url
        embed['fields'].append(
            {
                'name': 'Oeffnen',
                'value': f'[Turnierübersicht öffnen]({url})',
                'inline': False,
            }
        )

    if brand_icon_url:
        embed['author']['icon_url'] = brand_icon_url

    return {
        'allowed_mentions': {'parse': []},
        'embeds': [embed],
    }

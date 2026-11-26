"""
byceps.services.netsession_tourney.discord_payloads_forum
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Payloads for the Discord forum thread of a tournament.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .dbmodels import (
    DbNetsessionTourneyTournament,
)
from .notification_urls import (
    build_absolute_notification_url,
)
from .site_paths import (
    build_site_tournament_overview_path,
)


def build_discord_forum_thread_payload(
    db_tournament: DbNetsessionTourneyTournament,
) -> dict[str, Any]:
    url = build_absolute_notification_url(
        db_tournament.party_id,
        build_site_tournament_overview_path(db_tournament.slug),
    )
    brand_icon_url = build_absolute_notification_url(
        db_tournament.party_id, '/static_sites/netsession/icon-192.png'
    )
    image_url = _build_discord_forum_thread_image_url(db_tournament)
    description_lines = _build_discord_forum_thread_description_lines(
        db_tournament
    )

    fields = _build_discord_forum_thread_fields(db_tournament, url)

    embed: dict[str, Any] = {
        'author': {'name': 'Netsession Turniere'},
        'title': db_tournament.title[:256],
        'description': '\n'.join(description_lines)[:4096],
        'color': 0xFF2B00,
        'fields': fields,
        'footer': {'text': 'Netsession Turniere'},
        'timestamp': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
    }
    _add_discord_forum_thread_embed_links(
        embed, url=url, brand_icon_url=brand_icon_url, image_url=image_url
    )

    payload: dict[str, Any] = {
        'name': db_tournament.title[:100],
        'auto_archive_duration': 10080,
        'message': {
            'allowed_mentions': {'parse': []},
            'embeds': [embed],
        },
    }
    if db_tournament.discord_applied_tag_ids:
        payload['applied_tags'] = db_tournament.discord_applied_tag_ids

    return payload


def _build_discord_forum_thread_image_url(
    db_tournament: DbNetsessionTourneyTournament,
) -> str | None:
    if not db_tournament.discord_forum_image_url:
        return None

    return build_absolute_notification_url(
        db_tournament.party_id, db_tournament.discord_forum_image_url
    )


def _build_discord_forum_thread_description_lines(
    db_tournament: DbNetsessionTourneyTournament,
) -> list[str]:
    description_lines = [f'**{db_tournament.title}**']
    if db_tournament.subtitle:
        description_lines.append(db_tournament.subtitle)
    description_lines.append(
        'Der Discord-Thread für dieses Turnier wurde eingerichtet.'
    )
    return description_lines


def _build_discord_forum_thread_fields(
    db_tournament: DbNetsessionTourneyTournament, url: str | None
) -> list[dict[str, Any]]:
    fields = [
        {
            'name': 'Turnier',
            'value': db_tournament.title[:1024],
            'inline': True,
        },
    ]
    if db_tournament.game:
        fields.append(
            {
                'name': 'Spiel',
                'value': db_tournament.game[:1024],
                'inline': True,
            }
        )
    if db_tournament.starts_at is not None:
        fields.append(
            {
                'name': 'Start',
                'value': db_tournament.starts_at.strftime('%d.%m.%Y %H:%M')[
                    :1024
                ],
                'inline': True,
            }
        )
    if url:
        fields.append(
            {
                'name': 'Link',
                'value': f'[Turnierseite öffnen]({url})',
                'inline': False,
            }
        )
    return fields


def _add_discord_forum_thread_embed_links(
    embed: dict[str, Any],
    *,
    url: str | None,
    brand_icon_url: str | None,
    image_url: str | None,
) -> None:
    if url:
        embed['url'] = url
    if brand_icon_url:
        embed['author']['icon_url'] = brand_icon_url
    if image_url:
        embed['image'] = {'url': image_url}

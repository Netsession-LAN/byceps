"""
byceps.services.netsession_tourney.discord_payloads
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Payloads of Discord forum posts and events.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .dbmodels import (
    DbNetsessionTourneyDiscordOutbox,
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyTournament,
)
from .discord_result_summaries import (
    build_discord_match_completed_description,
    build_discord_match_completed_fields,
    build_discord_match_result_summary,
    build_discord_tournament_finished_description,
    build_discord_tournament_finished_fields,
    build_discord_tournament_result_summary,
)
from .models import (
    ParticipantID,
    Stage,
)
from .notification_urls import (
    build_absolute_notification_url,
)
from .site_paths import (
    build_site_match_path,
    build_site_tournament_overview_path,
)


def build_discord_tournament_finished_payload(
    db_tournament: DbNetsessionTourneyTournament,
) -> dict[str, Any]:
    payload: dict[str, Any] = {'slug': db_tournament.slug}
    result_summary = build_discord_tournament_result_summary(db_tournament)
    if result_summary:
        payload['result_summary'] = result_summary
    return payload


def build_discord_match_completed_payload(
    db_tournament: DbNetsessionTourneyTournament,
    db_match: DbNetsessionTourneyMatch,
    stage: Stage,
    db_slots: list[DbNetsessionTourneyMatchSlot],
    db_participants_by_id: dict[ParticipantID, DbNetsessionTourneyParticipant],
    winner_slot: int | None,
    score_data: dict[str, Any],
    ranking_data: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'stage_name': stage.name,
        'match_label': f'Match #{db_match.match_no}',
        'url': build_site_match_path(db_tournament.slug, db_match.id),
    }

    result_summary = build_discord_match_result_summary(
        stage=stage,
        db_slots=db_slots,
        db_participants_by_id=db_participants_by_id,
        winner_slot=winner_slot,
        score_data=score_data,
        ranking_data=ranking_data,
    )
    if result_summary:
        payload['result_summary'] = result_summary

    return payload


@dataclass(frozen=True, kw_only=True)
class _DiscordEventPresentation:
    embed_title: str
    description: str
    url: str | None
    color: int


def build_discord_message_payload(
    db_tournament: DbNetsessionTourneyTournament,
    db_row: DbNetsessionTourneyDiscordOutbox,
) -> dict[str, Any]:
    payload_data = db_row.payload_json or {}
    event_name = db_row.event_name
    url = build_absolute_notification_url(
        db_tournament.party_id,
        build_site_tournament_overview_path(db_tournament.slug),
    )
    brand_icon_url = build_absolute_notification_url(
        db_tournament.party_id, '/static_sites/netsession/icon-192.png'
    )

    presentation = _build_discord_event_presentation(
        db_tournament, event_name, payload_data, url
    )
    embed_title = presentation.embed_title
    url = presentation.url

    fields = _build_discord_message_fields(
        db_tournament, event_name, payload_data, embed_title, url
    )

    embed: dict[str, Any] = {
        'author': {'name': 'Netsession Turniere'},
        'title': embed_title[:256],
        'description': presentation.description[:4096],
        'color': presentation.color,
        'fields': fields,
        'footer': {'text': 'Netsession Turniere'},
        'timestamp': db_row.created_at.replace(microsecond=0).isoformat() + 'Z',
    }
    if url:
        embed['url'] = url
    if brand_icon_url:
        embed['author']['icon_url'] = brand_icon_url

    return {
        'allowed_mentions': {'parse': []},
        'embeds': [embed],
    }


_DISCORD_DEFAULT_COLOR = 0xFF2B00
_DISCORD_DEFAULT_DESCRIPTION = 'Es gibt ein neues Turnier-Update.'


def _build_discord_event_presentation(
    db_tournament: DbNetsessionTourneyTournament,
    event_name: str,
    payload_data: dict[str, Any],
    url: str | None,
) -> _DiscordEventPresentation:
    """Return embed title, description, link and color for the event."""
    build_presentation = _DISCORD_EVENT_PRESENTATION_BUILDERS.get(
        event_name, _build_discord_generic_update_presentation
    )
    return build_presentation(db_tournament, payload_data, url)


def _build_discord_manual_announcement_presentation(
    db_tournament: DbNetsessionTourneyTournament,
    payload_data: dict[str, Any],
    url: str | None,
) -> _DiscordEventPresentation:
    description = (
        str(payload_data.get('body') or '').strip()
        or _DISCORD_DEFAULT_DESCRIPTION
    )
    return _DiscordEventPresentation(
        embed_title='Turnier-Update',
        description=description,
        url=_get_discord_custom_url(db_tournament, payload_data, url),
        color=_DISCORD_DEFAULT_COLOR,
    )


def _build_discord_match_completed_presentation(
    db_tournament: DbNetsessionTourneyTournament,
    payload_data: dict[str, Any],
    url: str | None,
) -> _DiscordEventPresentation:
    description = build_discord_match_completed_description(
        db_tournament.title, payload_data
    )
    return _DiscordEventPresentation(
        embed_title='Match beendet',
        description=description,
        url=_get_discord_custom_url(db_tournament, payload_data, url),
        color=0x3B82F6,
    )


def _get_discord_custom_url(
    db_tournament: DbNetsessionTourneyTournament,
    payload_data: dict[str, Any],
    url: str | None,
) -> str | None:
    """Return the payload's own link (made absolute), if any, else `url`."""
    custom_url = str(payload_data.get('url') or '').strip()
    if custom_url:
        return build_absolute_notification_url(
            db_tournament.party_id, custom_url
        )
    return url


def _build_discord_stage_started_presentation(
    db_tournament: DbNetsessionTourneyTournament,
    payload_data: dict[str, Any],
    url: str | None,
) -> _DiscordEventPresentation:
    title = db_tournament.title
    stage_name = str(payload_data.get('stage_name') or '').strip()
    description = (
        f'**{title}**\n{stage_name} ist gestartet.'
        if stage_name
        else f'**{title}**\nEine neue Phase ist gestartet.'
    )
    return _DiscordEventPresentation(
        embed_title='Phase gestartet',
        description=description,
        url=url,
        color=0xF97316,
    )


def _build_discord_tournament_finished_presentation(
    db_tournament: DbNetsessionTourneyTournament,
    payload_data: dict[str, Any],
    url: str | None,
) -> _DiscordEventPresentation:
    description = build_discord_tournament_finished_description(
        db_tournament.title, payload_data
    )
    return _DiscordEventPresentation(
        embed_title='Turnier beendet',
        description=description,
        url=url,
        color=0x10B981,
    )


def _build_discord_tournament_canceled_presentation(
    db_tournament: DbNetsessionTourneyTournament,
    payload_data: dict[str, Any],
    url: str | None,
) -> _DiscordEventPresentation:
    return _DiscordEventPresentation(
        embed_title='Turnier abgesagt',
        description=f'**{db_tournament.title}**\nDas Turnier wurde abgesagt.',
        url=url,
        color=0xEF4444,
    )


def _build_discord_tournament_live_presentation(
    db_tournament: DbNetsessionTourneyTournament,
    payload_data: dict[str, Any],
    url: str | None,
) -> _DiscordEventPresentation:
    return _DiscordEventPresentation(
        embed_title='Turnier live',
        description=f'**{db_tournament.title}**\nDas Turnier ist jetzt live.',
        url=url,
        color=_DISCORD_DEFAULT_COLOR,
    )


def _build_discord_generic_update_presentation(
    db_tournament: DbNetsessionTourneyTournament,
    payload_data: dict[str, Any],
    url: str | None,
) -> _DiscordEventPresentation:
    return _DiscordEventPresentation(
        embed_title='Turnier-Update',
        description=(
            f'**{db_tournament.title}**\n{_DISCORD_DEFAULT_DESCRIPTION}'
        ),
        url=url,
        color=_DISCORD_DEFAULT_COLOR,
    )


_DISCORD_EVENT_PRESENTATION_BUILDERS: dict[
    str,
    Callable[
        [DbNetsessionTourneyTournament, dict[str, Any], str | None],
        _DiscordEventPresentation,
    ],
] = {
    'manual_announcement': _build_discord_manual_announcement_presentation,
    'match_completed': _build_discord_match_completed_presentation,
    'stage_started': _build_discord_stage_started_presentation,
    'tournament_finished': _build_discord_tournament_finished_presentation,
    'tournament_canceled': _build_discord_tournament_canceled_presentation,
    'tournament_live': _build_discord_tournament_live_presentation,
}


def _build_discord_message_fields(
    db_tournament: DbNetsessionTourneyTournament,
    event_name: str,
    payload_data: dict[str, Any],
    embed_title: str,
    url: str | None,
) -> list[dict[str, Any]]:
    fields = [
        {
            'name': 'Turnier',
            'value': db_tournament.title[:1024],
            'inline': True,
        },
        {'name': 'Ereignis', 'value': embed_title[:1024], 'inline': True},
    ]
    if url:
        fields.append(
            {
                'name': 'Oeffnen',
                'value': f'[Turnierseite öffnen]({url})',
                'inline': False,
            }
        )
    if event_name == 'tournament_finished':
        fields.extend(build_discord_tournament_finished_fields(payload_data))
    elif event_name == 'match_completed':
        fields.extend(build_discord_match_completed_fields(payload_data))
    return fields


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

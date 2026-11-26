"""
byceps.services.netsession_tourney.blueprints.site.presentation_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from datetime import timedelta

from flask_babel import format_datetime, gettext


def select_builder_stage_section(
    sections: list[dict], requested_key: str | None
) -> dict | None:
    if not sections:
        return None

    if requested_key:
        for section in sections:
            if section['key'] == requested_key:
                return section

    return sections[0]


def combine_stage_section_title(
    stage_title: str, subsection_title: str | None
) -> str:
    if subsection_title:
        return f'{stage_title} - {subsection_title}'
    return stage_title


def _build_round_time_range_label(
    matches,
    stage_duration_minutes_by_id,
) -> str | None:
    starts_at = []
    ends_at = []

    for match in matches:
        if match.scheduled_at is None:
            continue

        starts_at.append(match.scheduled_at)
        stage_duration_minutes = stage_duration_minutes_by_id.get(
            match.stage_id
        )
        end_at = (
            match.scheduled_at + timedelta(minutes=stage_duration_minutes)
            if stage_duration_minutes is not None
            else match.scheduled_at
        )
        ends_at.append(end_at)

    if not starts_at:
        return None

    round_starts_at = min(starts_at)
    round_ends_at = max(ends_at) if ends_at else round_starts_at

    return (
        f'{format_datetime(round_starts_at, "EEEE, HH:mm")} - '
        f'{format_datetime(round_ends_at, "EEEE, HH:mm")}'
    )


def build_match_overview_slot_data(
    slot,
    winner_slot: int | None,
    users_by_id,
) -> dict:
    if slot is None:
        return {
            'name': gettext('offen'),
            'image_url': None,
            'image_alt': None,
            'show_avatar': True,
            'is_bye': False,
            'is_winner': False,
        }

    participant = slot.get('participant')
    is_bye = bool(slot.get('is_bye'))
    image_url = None
    image_alt = None

    if (
        participant
        and participant.type.value == 'team'
        and participant.logo_url
    ):
        image_url = participant.logo_url
        image_alt = gettext('Team-Logo')
    elif participant and participant.user_id is not None:
        user = users_by_id.get(participant.user_id)
        if user is not None and user.avatar_url:
            image_url = user.avatar_url
            image_alt = gettext('Avatar')

    if is_bye:
        name = gettext('Freilos')
    elif participant is None:
        name = gettext('offen')
    else:
        name = participant.name

    return {
        'name': name,
        'image_url': image_url,
        'image_alt': image_alt,
        'show_avatar': not is_bye,
        'is_bye': is_bye,
        'is_winner': winner_slot is not None and slot['slot_no'] == winner_slot,
    }


def get_stage_duration_minutes(stage) -> int | None:
    if stage is None:
        return None

    raw_duration = stage.settings.get('match_duration_minutes')
    if isinstance(raw_duration, int) and raw_duration > 0:
        return raw_duration
    if isinstance(raw_duration, str) and raw_duration.isdigit():
        parsed = int(raw_duration)
        if parsed > 0:
            return parsed

    return None

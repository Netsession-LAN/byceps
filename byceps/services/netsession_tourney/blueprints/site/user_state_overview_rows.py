"""
byceps.services.netsession_tourney.blueprints.site.user_state_overview_rows
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The current user's matches on the tournament overview page.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from datetime import datetime

from flask import url_for
from flask_babel import format_datetime, gettext

from byceps.services.netsession_tourney.enum_labels import enum_label
from byceps.services.netsession_tourney.models import MatchState

from .flatout2_public_rendering import get_flatout2_host_participant_id
from .stage_filters import _is_flatout2_stage


def _collect_opponent_names(
    slots, participants_by_id, current_participant_id
) -> list[str]:
    opponent_names = []
    for slot in slots:
        if slot.participant_id == current_participant_id:
            continue

        participant = participants_by_id.get(slot.participant_id)
        if participant is not None:
            opponent_names.append(participant.name)
        elif slot.participant_id is None:
            opponent_names.append(gettext('Freilos'))

    return opponent_names


def _get_result_score_display(result):
    if result is not None and isinstance(result.score, dict):
        return result.score.get('display')

    return None


def _build_opponent_label(
    is_flatout2_match: bool, participant_count: int, opponent_names
) -> str:
    if is_flatout2_match:
        return gettext(
            'Heat mit %(count)s Teilnehmern',
            count=participant_count,
        )

    return ', '.join(opponent_names) if opponent_names else gettext('Freilos')


def _build_current_user_overview_match_row(
    tournament,
    match,
    slots,
    results_by_match_id,
    participants_by_id,
    stages_by_id,
    match_labels_by_id,
    current_participant_id,
) -> dict:
    is_flatout2_match = _is_flatout2_stage(stages_by_id.get(match.stage_id))
    participant_count = len(
        [slot for slot in slots if slot.participant_id is not None]
    )
    opponent_names = _collect_opponent_names(
        slots, participants_by_id, current_participant_id
    )
    result = results_by_match_id.get(match.id)
    score_display = _get_result_score_display(result)

    return {
        'match': match,
        'url': url_for(
            'netsession_tourney.view_match',
            slug=tournament.slug,
            match_id=match.id,
        ),
        'match_label': match_labels_by_id.get(
            match.id, f'{gettext("Match")} #{match.match_no}'
        ),
        'stage_name': (
            stages_by_id[match.stage_id].name
            if match.stage_id in stages_by_id
            else '-'
        ),
        'opponent_label': _build_opponent_label(
            is_flatout2_match, participant_count, opponent_names
        ),
        'scheduled_at_label': (
            format_datetime(match.scheduled_at, 'short')
            if match.scheduled_at is not None
            else '-'
        ),
        'state_label': enum_label(match.state),
        'score_display': score_display,
        'is_flatout2_match': is_flatout2_match,
        'is_host': (
            get_flatout2_host_participant_id(match)
            == str(current_participant_id)
        ),
    }


def _current_user_overview_match_sort_key(row) -> tuple:
    return (
        row['match'].state == MatchState.completed,
        row['match'].scheduled_at or datetime.max,
        row['match'].round_no,
        row['match'].match_no,
    )


def build_current_user_overview_match_rows(
    tournament,
    matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    stages_by_id,
    match_labels_by_id,
    current_participant_id,
):
    if current_participant_id is None:
        return []

    rows = []

    for match in matches:
        slots = slots_by_match_id.get(match.id, [])
        if not any(
            slot.participant_id == current_participant_id for slot in slots
        ):
            continue

        rows.append(
            _build_current_user_overview_match_row(
                tournament,
                match,
                slots,
                results_by_match_id,
                participants_by_id,
                stages_by_id,
                match_labels_by_id,
                current_participant_id,
            )
        )

    return sorted(rows, key=_current_user_overview_match_sort_key)

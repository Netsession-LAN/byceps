"""
byceps.services.netsession_tourney.blueprints.site.stage_render_team_history
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Match history rows of a team.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.score_parsing import (
    get_ffa_points_per_kill,
)

from .round_based_public_rendering import _get_score_display
from .stage_filters import _is_ffa_scoring_stage, _is_flatout2_stage
from .stage_render_ffa_matches import (
    _get_ffa_placement_by_slot_no,
    get_ffa_points_by_slot_no,
    get_slot_keyed_value,
    parse_score_int,
)


def build_team_history_rows(
    team,
    matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    match_labels_by_id,
    stages_by_id,
):
    history_rows = []
    for match in matches:
        history_row = _build_team_history_row(
            team,
            match,
            slots_by_match_id,
            results_by_match_id,
            participants_by_id,
            match_labels_by_id,
            stages_by_id,
        )
        if history_row is not None:
            history_rows.append(history_row)

    return history_rows


def _build_team_history_row(
    team,
    match,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    match_labels_by_id,
    stages_by_id,
) -> dict | None:
    slots = slots_by_match_id.get(match.id, [])
    own_slot = _find_own_slot(slots, team)
    if own_slot is None:
        return None

    opponents = _get_opponents(slots, team, participants_by_id)
    stage = stages_by_id.get(match.stage_id)
    result = results_by_match_id.get(match.id)
    outcome = _get_outcome(result, own_slot)

    is_ffa_scoring_match = _is_ffa_scoring_stage(stage)
    is_flatout2_match = _is_flatout2_stage(stage)
    placement = None
    points = 0
    total_points = 0
    if is_ffa_scoring_match:
        placement, points, total_points = _get_ffa_scores(
            stage, result, slots, own_slot
        )

    return {
        'match': match,
        'is_ffa_scoring_match': is_ffa_scoring_match,
        'is_flatout2_match': is_flatout2_match,
        'match_label': match_labels_by_id.get(
            match.id, f'{gettext("Match")} #{match.match_no}'
        ),
        'own_slot': own_slot,
        'opponents': [opponent for opponent in opponents if opponent],
        'result': result,
        'outcome': outcome,
        'left_team_name': _get_team_name_for_slot(slots, 1, participants_by_id),
        'right_team_name': _get_team_name_for_slot(
            slots, 2, participants_by_id
        ),
        'score_display': _get_score_display(result),
        'score_left': _get_score_side(result, 0),
        'score_right': _get_score_side(result, 1),
        'left_is_own_team': own_slot.slot_no == 1,
        'right_is_own_team': own_slot.slot_no == 2,
        'left_is_bye': _is_bye_slot(slots, 1),
        'right_is_bye': _is_bye_slot(slots, 2),
        'placement': placement,
        'points': points,
        'total_points': total_points,
    }


def _find_own_slot(slots, team):
    return next(
        (
            slot
            for slot in slots
            if slot.participant_id is not None
            and slot.participant_id == team.id
        ),
        None,
    )


def _get_opponents(slots, team, participants_by_id) -> list:
    return [
        participants_by_id.get(slot.participant_id)
        for slot in slots
        if slot.participant_id is not None and slot.participant_id != team.id
    ]


def _get_outcome(result, own_slot) -> str:
    if result and result.winner_slot is not None:
        return 'win' if result.winner_slot == own_slot.slot_no else 'loss'
    return 'pending'


def _get_ffa_scores(stage, result, slots, own_slot):
    """Return placement, points and total points (including kill points)."""
    placement = _get_ffa_placement_by_slot_no(result, slots).get(
        own_slot.slot_no
    )
    points = get_ffa_points_by_slot_no(result, slots).get(own_slot.slot_no, 0)
    raw_kills = get_slot_keyed_value(
        _get_raw_score_slots(result), own_slot.slot_no
    )
    kills = parse_score_int(raw_kills)
    points_per_kill = get_ffa_points_per_kill(
        stage.settings if stage is not None else {}
    )
    total_points = points + (kills * points_per_kill)
    return placement, points, total_points


def _get_raw_score_slots(result) -> dict:
    raw_score_slots = {}
    if result and isinstance(result.score.get('slots'), dict):
        raw_score_slots = result.score.get('slots')
    return raw_score_slots


def _get_team_name_for_slot(slots, slot_no: int, participants_by_id) -> str:
    slot = next((item for item in slots if item.slot_no == slot_no), None)
    if slot is None:
        return '-'

    if slot.participant_id is None:
        return gettext('Freilos')

    participant = participants_by_id.get(slot.participant_id)
    if participant is None:
        return gettext('offen')

    return participant.name


def _is_bye_slot(slots, slot_no: int) -> bool:
    slot = next((item for item in slots if item.slot_no == slot_no), None)
    if slot is None:
        return False

    return slot.participant_id is None


def _get_score_side(result, index: int) -> str | None:
    score_display = _get_score_display(result)
    if score_display == '-' or ':' not in score_display:
        return None

    parts = score_display.split(':', 1)
    if len(parts) != 2:
        return None

    return parts[index].strip()

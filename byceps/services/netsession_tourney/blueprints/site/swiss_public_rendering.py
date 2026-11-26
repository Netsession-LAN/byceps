"""
byceps.services.netsession_tourney.blueprints.site.swiss_public_rendering
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from flask_babel import gettext

from byceps.services.netsession_tourney.models import StageType
from byceps.services.netsession_tourney.swiss_stage import (
    build_swiss_round_layout,
)
from byceps.services.netsession_tourney.swiss_thresholds import (
    get_round_count_for_swiss_stage,
    get_swiss_threshold_for_stage,
)

from .stage_render_grouping import (
    group_matches_by_stage_id,
    sort_stage_match_groups,
)
from .swiss_public_round_parts import build_logical_round, SwissRenderData


def build_swiss_bracket_sections(
    matches,
    slots_by_match_id,
    results_by_match_id,
    slot_scores_by_match_id,
    participants_by_id,
    users_by_id,
    match_labels_by_id,
    stages_by_id,
):
    data = SwissRenderData(
        slots_by_match_id=slots_by_match_id,
        results_by_match_id=results_by_match_id,
        slot_scores_by_match_id=slot_scores_by_match_id,
        participants_by_id=participants_by_id,
        users_by_id=users_by_id,
        match_labels_by_id=match_labels_by_id,
    )

    matches_by_stage_id = group_matches_by_stage_id(matches)

    sections = []
    for stage_id, stage_matches in sort_stage_match_groups(
        matches_by_stage_id, stages_by_id
    ):
        stage = stages_by_id.get(stage_id)
        if stage is None or stage.type != StageType.swiss:
            continue

        logical_rounds = _build_logical_rounds(stage, stage_matches, data)

        sections.append(
            {
                'key': str(stage_id),
                'title': stage.name,
                'rounds': _build_display_rounds(logical_rounds),
            }
        )

    return sections


def _build_logical_rounds(
    stage, stage_matches, data: SwissRenderData
) -> list[dict]:
    participant_count = _count_stage_participants(
        stage_matches, data.slots_by_match_id
    )
    round_count = get_round_count_for_swiss_stage(
        stage, participant_count=participant_count
    )
    layout = build_swiss_round_layout(participant_count, round_count)
    threshold = get_swiss_threshold_for_stage(
        stage, participant_count=participant_count
    )
    matches_by_round_no = defaultdict(list)
    for match in stage_matches:
        matches_by_round_no[match.round_no].append(match)

    previous_round_match_id_by_participant_id: dict[Any, Any] = {}
    cumulative_points_by_participant_id = defaultdict(int)
    logical_rounds = []
    for round_layout in layout:
        round_matches = sorted(
            matches_by_round_no.get(round_layout['round_no'], []),
            key=lambda match: match.match_no,
        )
        logical_rounds.append(
            build_logical_round(
                round_layout,
                round_matches,
                threshold,
                previous_round_match_id_by_participant_id,
                cumulative_points_by_participant_id,
                data,
            )
        )

        previous_round_match_id_by_participant_id = (
            _map_match_id_by_participant_id(
                round_matches, data.slots_by_match_id
            )
        )

    return logical_rounds


def _count_stage_participants(stage_matches, slots_by_match_id) -> int:
    return len(
        {
            slot.participant_id
            for slots in (
                slots_by_match_id.get(match.id, []) for match in stage_matches
            )
            for slot in slots
            if slot.participant_id is not None
        }
    )


def _map_match_id_by_participant_id(round_matches, slots_by_match_id) -> dict:
    return {
        slot.participant_id: match.id
        for match in round_matches
        for slot in slots_by_match_id.get(match.id, [])
        if slot.participant_id is not None
    }


def _build_display_rounds(logical_rounds: list[dict]) -> list[dict]:
    rounds = [
        _build_display_round(logical_rounds, index)
        for index in range(len(logical_rounds))
    ]

    if logical_rounds and logical_rounds[-1]['outcomes']:
        rounds.append(_build_result_round(logical_rounds[-1]['outcomes']))

    return rounds


def _build_display_round(logical_rounds: list[dict], index: int) -> dict:
    logical_round = logical_rounds[index]
    incoming_outcomes = (
        logical_rounds[index - 1]['outcomes'] if index > 0 else []
    )
    blocks = [
        {'kind': 'outcome', 'item': outcome} for outcome in incoming_outcomes
    ] + [
        {'kind': 'pool', 'item': pool_view}
        for pool_view in logical_round['pools']
    ]
    return {
        'round_no': logical_round['round_no'],
        'display_title': gettext('Runde') + f' {logical_round["round_no"]}',
        'is_sidecar': False,
        'pools': logical_round['pools'],
        'outcomes': incoming_outcomes,
        'blocks': blocks,
    }


def _build_result_round(outcomes: list[dict]) -> dict:
    return {
        'round_no': None,
        'display_title': gettext('Ergebnis'),
        'is_sidecar': True,
        'pools': [],
        'outcomes': outcomes,
        'blocks': [
            {'kind': 'outcome', 'item': outcome} for outcome in outcomes
        ],
    }

"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_form_data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Data of the stage form for an existing stage.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.blueprints.admin.stage_builder_placement_points import (
    get_first_positive_int,
    get_max_rule_place,
)
from byceps.services.netsession_tourney.models import (
    StageType,
)
from byceps.services.netsession_tourney.result_report_mode import (
    RESULT_REPORT_MODE_ADMIN_ONLY,
)
from byceps.services.netsession_tourney.score_parsing import (
    get_ffa_points_per_kill,
)
from byceps.services.netsession_tourney.swiss_thresholds import (
    get_configured_swiss_threshold,
    get_swiss_threshold_for_round_count,
)


def stage_to_form_data(stage) -> dict:
    result_report_mode = stage.settings.get(
        'result_report_mode', 'both_must_confirm'
    )
    if _is_ffa_scoring_stage_type(stage.type):
        result_report_mode = RESULT_REPORT_MODE_ADMIN_ONLY

    swiss_threshold = get_configured_swiss_threshold(stage.settings)
    if swiss_threshold is None and stage.type == StageType.swiss:
        raw_round_count = stage.settings.get('round_count')
        try:
            swiss_threshold = get_swiss_threshold_for_round_count(
                int(raw_round_count)
            )
        except TypeError, ValueError:
            swiss_threshold = None
    if swiss_threshold not in {2, 3, 4}:
        swiss_threshold = None

    return {
        'type': stage.type.value,
        'name': stage.name,
        'round_count': stage.settings.get('round_count'),
        'swiss_threshold': swiss_threshold,
        'max_players_per_match': stage.settings.get('max_players_per_match'),
        'group_size': stage.settings.get('group_size'),
        'placement_points': _format_ffa_placement_points_rules(
            stage.settings.get('placement_points_rules')
        ),
        'points_per_kill': get_ffa_points_per_kill(stage.settings),
        'match_duration_minutes': stage.settings.get('match_duration_minutes'),
        'max_matches_per_round': stage.settings.get('max_matches_per_round'),
        'break_between_rounds_minutes': stage.settings.get(
            'break_between_rounds_minutes'
        ),
        'result_report_mode': result_report_mode,
    }


def _format_ffa_placement_points_rules(rules) -> str:
    if not isinstance(rules, list):
        return ''

    normalized_rules = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue

        try:
            from_place = int(rule.get('from_place'))
            to_place = int(rule.get('to_place'))
            points = int(rule.get('points'))
        except TypeError, ValueError:
            continue

        normalized_rules.append((from_place, to_place, points))

    normalized_rules.sort(key=lambda item: (item[0], item[1], -item[2]))

    lines = []
    for from_place, to_place, points in normalized_rules:
        place_label = (
            str(from_place)
            if from_place == to_place
            else f'{from_place}-{to_place}'
        )
        lines.append(f'{place_label} = {points}')

    return '\n'.join(lines)


def _is_ffa_scoring_stage_type(stage_type: StageType | None) -> bool:
    return stage_type in {
        StageType.ffa_simple,
        StageType.ffa_single_elimination,
    }


def is_ffa_result_stage_type(stage_type: StageType | None) -> bool:
    return stage_type in {
        StageType.ffa_simple,
        StageType.ffa_single_elimination,
        StageType.ffa_flatout2_single_elimination,
    }


def get_ffa_placement_points_row_count(
    tournament,
    placement_points_text: str | None,
    *,
    stage_type: StageType | None = None,
    max_players_per_match: int | None = None,
    existing_settings: dict | None = None,
) -> int:
    if stage_type == StageType.ffa_single_elimination:
        parsed = get_first_positive_int(
            _get_max_players_per_match_candidates(
                max_players_per_match, existing_settings
            )
        )
        if parsed is not None:
            return parsed

    participant_limit = getattr(tournament, 'participant_limit', None)
    if (
        stage_type != StageType.ffa_single_elimination
        and isinstance(participant_limit, int)
        and participant_limit > 0
    ):
        return participant_limit

    return get_max_rule_place(placement_points_text)


def _get_max_players_per_match_candidates(
    max_players_per_match: int | None, existing_settings: dict | None
) -> list:
    candidates = [max_players_per_match]
    if isinstance(existing_settings, dict):
        candidates.append(existing_settings.get('max_players_per_match'))
    return candidates

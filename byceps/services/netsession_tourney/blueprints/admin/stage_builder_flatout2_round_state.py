"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_round_state
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Round state of the manual FlatOut 2 generation form (see
`stage_builder_flatout2_form`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_form import (
    _get_form_value,
    FLATOUT2_MAX_MATCH_COUNT_PER_ROUND,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_match_state import (
    _build_match_state,
    _build_race_state,
)
from byceps.services.netsession_tourney.flatout2 import (
    FLATOUT2_MAX_RACES_PER_ROUND,
)


def build_flatout2_round_state(
    stage,
    round_no: int,
    *,
    default_round: dict,
    raw_match_blueprints: dict,
    posted_form,
    max_players_per_match: int,
    participant_choice_values: set[str],
) -> dict:
    match_count = _get_state_match_count(posted_form, round_no, default_round)
    default_round_races = _get_default_round_races(
        default_round, raw_match_blueprints, round_no
    )
    race_count = _get_state_race_count(
        posted_form, round_no, default_round_races
    )

    round_races = [
        _build_race_state(
            posted_form, round_no, race_no, default_round_races, race_count
        )
        for race_no in range(1, FLATOUT2_MAX_RACES_PER_ROUND + 1)
    ]

    matches = [
        _build_match_state(
            posted_form,
            round_no,
            match_no,
            raw_match_blueprints=raw_match_blueprints,
            match_count=match_count,
            max_players_per_match=max_players_per_match,
            participant_choice_values=participant_choice_values,
        )
        for match_no in range(1, FLATOUT2_MAX_MATCH_COUNT_PER_ROUND + 1)
    ]

    return {
        'round_no': round_no,
        'display_title': stage.name,
        'is_active': True,
        'match_count': match_count,
        'race_count': race_count,
        'races': round_races,
        'matches': matches,
    }


def _get_posted_value(posted_form, name: str) -> str:
    if posted_form is None:
        return ''
    return _get_form_value(posted_form, name)


def _parse_int_or_zero(raw_value: str) -> int:
    if not raw_value:
        return 0
    try:
        return int(raw_value)
    except ValueError:
        return 0


def _get_state_match_count(posted_form, round_no: int, default_round) -> int:
    match_count = _parse_int_or_zero(
        _get_posted_value(posted_form, f'flatout2_match_count_round_{round_no}')
    )
    if match_count < 1 or match_count > FLATOUT2_MAX_MATCH_COUNT_PER_ROUND:
        match_count = _get_default_match_count(default_round)
    return max(1, min(match_count, FLATOUT2_MAX_MATCH_COUNT_PER_ROUND))


def _get_default_match_count(default_round) -> int:
    try:
        return int(default_round.get('match_count') or 1)
    except TypeError, ValueError:
        return 1


def _get_default_round_races(
    default_round, raw_match_blueprints: dict, round_no: int
) -> list:
    default_round_races = default_round.get('races')
    if not isinstance(default_round_races, list):
        default_round_races = []
    if not default_round_races:
        # Compatibility with older saved shape where races lived per match blueprint.
        default_round_races = (
            _get_legacy_round_races(raw_match_blueprints, round_no)
            or default_round_races
        )
    return default_round_races


def _get_legacy_round_races(
    raw_match_blueprints: dict, round_no: int
) -> list | None:
    legacy_blueprint = raw_match_blueprints.get(f'{round_no}:1')
    if not isinstance(legacy_blueprint, dict):
        return None
    legacy_races = legacy_blueprint.get('races')
    return legacy_races if isinstance(legacy_races, list) else None


def _get_state_race_count(
    posted_form, round_no: int, default_round_races: list
) -> int:
    race_count = _parse_int_or_zero(
        _get_posted_value(posted_form, f'flatout2_race_count_round_{round_no}')
    )
    if race_count < 1 or race_count > FLATOUT2_MAX_RACES_PER_ROUND:
        race_count = min(
            max(len(default_round_races), 1),
            FLATOUT2_MAX_RACES_PER_ROUND,
        )
    return race_count

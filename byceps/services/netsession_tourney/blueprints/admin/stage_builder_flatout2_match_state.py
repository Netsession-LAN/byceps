"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_match_state
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Match and race state of the manual FlatOut 2 generation form
(see `stage_builder_flatout2_round_state`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_form import (
    _get_form_value,
)
from byceps.services.netsession_tourney.flatout2 import (
    FLATOUT2_MODE_SPECS,
)


def _build_race_state(
    posted_form,
    round_no: int,
    race_no: int,
    default_round_races: list,
    race_count: int,
) -> dict:
    default_race = _get_default_race(default_round_races, race_no)
    mode = _get_race_value(
        posted_form, 'mode', round_no, race_no, default_race, 'single_race'
    )
    if mode not in FLATOUT2_MODE_SPECS:
        mode = 'single_race'
    track = _get_race_value(
        posted_form, 'track', round_no, race_no, default_race, ''
    )
    vehicle = _get_race_value(
        posted_form, 'vehicle', round_no, race_no, default_race, ''
    )
    return {
        'race_no': race_no,
        'mode': mode,
        'track': track,
        'vehicle': vehicle,
        'is_active': race_no <= race_count,
    }


def _get_default_race(default_round_races: list, race_no: int) -> dict:
    return (
        default_round_races[race_no - 1]
        if race_no - 1 < len(default_round_races)
        and isinstance(default_round_races[race_no - 1], dict)
        else {}
    )


def _get_race_value(
    posted_form,
    field: str,
    round_no: int,
    race_no: int,
    default_race: dict,
    fallback: str,
) -> str:
    if posted_form is not None:
        return _get_form_value(
            posted_form, f'flatout2_{field}_round_{round_no}_race_{race_no}'
        )
    return str(default_race.get(field) or fallback).strip()


def _build_match_state(
    posted_form,
    round_no: int,
    match_no: int,
    *,
    raw_match_blueprints: dict,
    match_count: int,
    max_players_per_match: int,
    participant_choice_values: set[str],
) -> dict:
    match_key = f'{round_no}:{match_no}'
    default_participant_ids = _get_blueprint_participant_ids(
        raw_match_blueprints.get(match_key)
    )
    selected_participant_ids = [
        _get_selected_participant_id(
            posted_form,
            f'flatout2_participant_round_{round_no}_match_{match_no}_slot_{slot_no}',
            _get_default_participant_id(default_participant_ids, slot_no),
            participant_choice_values,
        )
        for slot_no in range(1, max_players_per_match + 1)
    ]

    return {
        'match_no': match_no,
        'match_key': match_key,
        'is_active': match_no <= match_count,
        'participant_ids': selected_participant_ids,
        'host_participant_id': (
            selected_participant_ids[0] if selected_participant_ids else ''
        ),
    }


def _get_blueprint_participant_ids(blueprint) -> list:
    if not isinstance(blueprint, dict):
        return []
    participant_ids = blueprint.get('participant_ids')
    return participant_ids if isinstance(participant_ids, list) else []


def _get_default_participant_id(
    default_participant_ids: list, slot_no: int
) -> str:
    return str(
        default_participant_ids[slot_no - 1]
        if slot_no - 1 < len(default_participant_ids)
        and default_participant_ids[slot_no - 1]
        else ''
    ).strip()


def _get_selected_participant_id(
    posted_form,
    field_name: str,
    default_value: str,
    participant_choice_values: set[str],
) -> str:
    raw_value = (
        _get_form_value(posted_form, field_name)
        if posted_form is not None
        else default_value
    )
    if raw_value not in participant_choice_values:
        return ''
    return raw_value

"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_form
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The state of the manual FlatOut 2 generation form as shown to the admin
(see `stage_builder_helpers`; the submitted configuration is parsed in
`stage_builder_flatout2_config`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.flatout2 import (
    FLATOUT2_MAX_RACES_PER_ROUND,
    FLATOUT2_MODE_SPECS,
)


FLATOUT2_MAX_MATCH_COUNT_PER_ROUND = 10


def get_flatout2_max_players_per_match(settings: dict) -> int:
    try:
        max_players_per_match = int(settings.get('max_players_per_match') or 8)
    except TypeError, ValueError:
        max_players_per_match = 8
    return max(2, min(max_players_per_match, 8))


def get_list_setting(settings: dict, key: str) -> list:
    value = settings.get(key)
    return value if isinstance(value, list) else []


def get_dict_setting(settings: dict, key: str) -> dict:
    value = settings.get(key)
    return value if isinstance(value, dict) else {}


def _get_form_value(form, name: str) -> str:
    return (form.get(name) or '').strip()


# form state


def build_flatout2_participant_choices(participants: list) -> list[dict]:
    return [
        {'value': str(participant.id), 'label': participant.name}
        for participant in sorted(
            participants, key=lambda item: item.name.casefold()
        )
    ]


def build_flatout2_round_defaults_by_no(raw_rounds: list) -> dict[int, dict]:
    round_defaults_by_no: dict[int, dict] = {}
    for index, raw_round in enumerate(raw_rounds, start=1):
        if not isinstance(raw_round, dict):
            continue
        round_defaults_by_no[_get_default_round_no(raw_round, index)] = (
            raw_round
        )
    return round_defaults_by_no


def _get_default_round_no(raw_round: dict, index: int) -> int:
    try:
        return int(raw_round.get('round_no') or index)
    except TypeError, ValueError:
        return index


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

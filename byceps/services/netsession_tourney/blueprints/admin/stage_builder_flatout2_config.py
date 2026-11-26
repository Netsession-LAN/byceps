"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Parsing of the submitted manual FlatOut 2 generation form, round by
round (see `stage_builder_helpers`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_form import (
    FLATOUT2_MAX_MATCH_COUNT_PER_ROUND,
)
from byceps.services.netsession_tourney.flatout2 import (
    FLATOUT2_MAX_RACES_PER_ROUND,
    FLATOUT2_MODE_SPECS,
    FLATOUT2_TRACK_SET_BY_MODE,
    FLATOUT2_VEHICLE_SET_BY_MODE,
)
from byceps.util.result import Err, Ok, Result


def _get_form_value(form, name: str) -> str:
    return (form.get(name) or '').strip()


def parse_flatout2_round_configuration(
    stage,
    round_no: int,
    request_form,
    participant_ids_by_str: dict,
    max_players_per_match: int,
) -> Result[tuple[dict, dict[str, dict], dict[tuple[int, int], dict]], str]:
    match_count_result = _parse_match_count(request_form, round_no)
    if match_count_result.is_err():
        return Err(match_count_result.unwrap_err())

    race_count_result = _parse_race_count(request_form, round_no)
    if race_count_result.is_err():
        return Err(race_count_result.unwrap_err())

    match_count = match_count_result.unwrap()
    race_count = race_count_result.unwrap()

    races_result = _parse_races(request_form, round_no, race_count)
    if races_result.is_err():
        return Err(races_result.unwrap_err())

    round_races = races_result.unwrap()
    round_configuration = {
        'round_no': round_no,
        'display_title': stage.name,
        'match_count': match_count,
        'race_count': race_count,
        'races': round_races,
    }

    assignments_result = _parse_match_assignments(
        request_form,
        round_no,
        match_count,
        round_races,
        participant_ids_by_str,
        max_players_per_match,
    )
    if assignments_result.is_err():
        return Err(assignments_result.unwrap_err())

    match_blueprints, match_settings = assignments_result.unwrap()
    return Ok((round_configuration, match_blueprints, match_settings))


def _parse_match_count(request_form, round_no: int) -> Result[int, str]:
    raw_match_count = _get_form_value(
        request_form, f'flatout2_match_count_round_{round_no}'
    )
    try:
        match_count = int(raw_match_count)
    except ValueError:
        match_count = 0
    if match_count < 1 or match_count > FLATOUT2_MAX_MATCH_COUNT_PER_ROUND:
        return Err(
            gettext(
                'Bitte für Runde %(round_no)s eine Matchanzahl zwischen 1 und %(max_count)s wählen.',
                round_no=round_no,
                max_count=FLATOUT2_MAX_MATCH_COUNT_PER_ROUND,
            )
        )
    return Ok(match_count)


def _parse_race_count(request_form, round_no: int) -> Result[int, str]:
    raw_race_count = _get_form_value(
        request_form, f'flatout2_race_count_round_{round_no}'
    )
    try:
        race_count = int(raw_race_count)
    except ValueError:
        race_count = 0
    if race_count < 1 or race_count > FLATOUT2_MAX_RACES_PER_ROUND:
        return Err(
            gettext(
                'Bitte für Runde %(round_no)s eine Rennanzahl zwischen 1 und %(max_count)s wählen.',
                round_no=round_no,
                max_count=FLATOUT2_MAX_RACES_PER_ROUND,
            )
        )
    return Ok(race_count)


def _parse_races(
    request_form, round_no: int, race_count: int
) -> Result[list[dict], str]:
    round_races = []
    for race_no in range(1, race_count + 1):
        race_result = _parse_race(request_form, round_no, race_no)
        if race_result.is_err():
            return Err(race_result.unwrap_err())
        round_races.append(race_result.unwrap())
    return Ok(round_races)


def _parse_race(request_form, round_no: int, race_no: int) -> Result[dict, str]:
    mode = _get_form_value(
        request_form, f'flatout2_mode_round_{round_no}_race_{race_no}'
    )
    if mode not in FLATOUT2_MODE_SPECS:
        return Err(
            gettext(
                'Bitte für Runde %(round_no)s, Rennen %(race_no)s einen gültigen Modus wählen.',
                round_no=round_no,
                race_no=race_no,
            )
        )
    track = _get_form_value(
        request_form, f'flatout2_track_round_{round_no}_race_{race_no}'
    )
    vehicle = _get_form_value(
        request_form, f'flatout2_vehicle_round_{round_no}_race_{race_no}'
    )
    if track not in FLATOUT2_TRACK_SET_BY_MODE[mode]:
        return Err(
            gettext(
                'Bitte für Runde %(round_no)s, Rennen %(race_no)s eine passende Strecke wählen.',
                round_no=round_no,
                race_no=race_no,
            )
        )
    if vehicle not in FLATOUT2_VEHICLE_SET_BY_MODE[mode]:
        return Err(
            gettext(
                'Bitte für Runde %(round_no)s, Rennen %(race_no)s ein gültiges Fahrzeug wählen.',
                round_no=round_no,
                race_no=race_no,
            )
        )
    return Ok(
        {
            'mode': mode,
            'track': track,
            'vehicle': vehicle,
        }
    )


def _parse_match_assignments(
    request_form,
    round_no: int,
    match_count: int,
    round_races: list[dict],
    participant_ids_by_str: dict,
    max_players_per_match: int,
) -> Result[tuple[dict[str, dict], dict[tuple[int, int], dict]], str]:
    match_blueprints: dict[str, dict] = {}
    match_settings_by_round_and_match_no: dict[tuple[int, int], dict] = {}
    assigned_participant_ids_for_round: set[str] = set()
    for match_no in range(1, match_count + 1):
        slots_result = _parse_match_slots(
            request_form,
            round_no,
            match_no,
            max_players_per_match,
            participant_ids_by_str,
            assigned_participant_ids_for_round,
        )
        if slots_result.is_err():
            return Err(slots_result.unwrap_err())

        participant_ids_for_match, real_participant_ids_for_match = (
            slots_result.unwrap()
        )
        host_participant_id = participant_ids_for_match[0]
        if real_participant_ids_for_match and host_participant_id is None:
            return Err(
                gettext(
                    'In Runde %(round_no)s, Match %(match_no)s muss Slot 1 belegt sein, da Slot 1 immer der Host ist.',
                    round_no=round_no,
                    match_no=match_no,
                )
            )

        match_key = f'{round_no}:{match_no}'
        match_blueprints[match_key] = {
            'participant_ids': participant_ids_for_match,
            'host_participant_id': host_participant_id,
        }
        match_settings_by_round_and_match_no[(round_no, match_no)] = {
            'host_participant_id': host_participant_id,
            'flatout2_races': round_races,
        }

    return Ok((match_blueprints, match_settings_by_round_and_match_no))


def _parse_match_slots(
    request_form,
    round_no: int,
    match_no: int,
    max_players_per_match: int,
    participant_ids_by_str: dict,
    assigned_participant_ids_for_round: set[str],
) -> Result[tuple[list[str | None], list[str]], str]:
    participant_ids_for_match: list[str | None] = []
    real_participant_ids_for_match: list[str] = []
    for slot_no in range(1, max_players_per_match + 1):
        raw_participant_id = _get_form_value(
            request_form,
            f'flatout2_participant_round_{round_no}_match_{match_no}_slot_{slot_no}',
        )
        if not raw_participant_id:
            participant_ids_for_match.append(None)
            continue
        error = _get_slot_assignment_error(
            raw_participant_id,
            round_no,
            match_no,
            participant_ids_by_str,
            real_participant_ids_for_match,
            assigned_participant_ids_for_round,
        )
        if error is not None:
            return Err(error)
        participant_ids_for_match.append(raw_participant_id)
        real_participant_ids_for_match.append(raw_participant_id)
        assigned_participant_ids_for_round.add(raw_participant_id)

    return Ok((participant_ids_for_match, real_participant_ids_for_match))


def _get_slot_assignment_error(
    raw_participant_id: str,
    round_no: int,
    match_no: int,
    participant_ids_by_str: dict,
    real_participant_ids_for_match: list[str],
    assigned_participant_ids_for_round: set[str],
) -> str | None:
    if raw_participant_id not in participant_ids_by_str:
        return gettext(
            'Die Teilnehmerzuordnung für Runde %(round_no)s, Match %(match_no)s ist ungültig.',
            round_no=round_no,
            match_no=match_no,
        )
    if raw_participant_id in real_participant_ids_for_match:
        return gettext(
            'Ein Teilnehmer darf in Runde %(round_no)s, Match %(match_no)s nur einmal vorkommen.',
            round_no=round_no,
            match_no=match_no,
        )
    if raw_participant_id in assigned_participant_ids_for_round:
        return gettext(
            'Ein Teilnehmer darf in Runde %(round_no)s nur einem Match zugewiesen sein.',
            round_no=round_no,
        )
    return None

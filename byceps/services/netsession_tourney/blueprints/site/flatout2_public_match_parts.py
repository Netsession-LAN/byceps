"""
byceps.services.netsession_tourney.blueprints.site.flatout2_public_match_parts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Participants, host and races of a FlatOut 2 match row.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.flatout2 import get_flatout2_mode_label


def _is_flatout2_host_slot(slot, current_host_participant_id: str) -> bool:
    return (
        bool(current_host_participant_id)
        and str(slot.participant_id) == current_host_participant_id
    )


def _flatout2_participant_sort_key(participant) -> tuple:
    return (
        participant['placement']
        if participant['placement'] is not None
        else 999999,
        -participant['kills_value'],
        participant['slot_no'],
        participant['name'].lower(),
    )


def _build_flatout2_match_participants(
    slots,
    result,
    participants_by_id,
    users_by_id,
    current_host_participant_id: str,
    *,
    build_participant_data,
    parse_slot_scores,
    get_placement_by_slot_no,
) -> list[dict]:
    slot_scores = parse_slot_scores(slots, result)
    placement_by_slot_no = get_placement_by_slot_no(result, slots)
    participants = [
        build_participant_data(
            slot,
            participants_by_id,
            users_by_id,
            result.winner_slot if result else None,
            slot_scores.get(slot.slot_no),
            placement_by_slot_no.get(slot.slot_no),
            is_host=_is_flatout2_host_slot(slot, current_host_participant_id),
        )
        for slot in slots
        if slot.participant_id is not None
    ]
    participants.sort(key=_flatout2_participant_sort_key)
    return participants


def _find_host_participant_name(participants) -> str | None:
    return next(
        (
            participant['name']
            for participant in participants
            if participant['is_host']
        ),
        None,
    )


def _get_raw_flatout2_round_races(stage, round_no: int):
    round_races = (stage.settings or {}).get('flatout2_round_races', {})
    return round_races.get(str(round_no)) or round_races.get(round_no, []) or []


def _get_flatout2_race_mode(race: dict) -> str:
    return str(race.get('mode') or '').strip() or 'single_race'


def get_flatout2_round_races_for_stage_round(
    stage, round_no: int
) -> list[dict]:
    raw_round_races = _get_raw_flatout2_round_races(stage, round_no)

    return [
        {
            **race,
            'mode_label': get_flatout2_mode_label(
                _get_flatout2_race_mode(race)
            ),
        }
        for race in raw_round_races
        if isinstance(race, dict)
    ]

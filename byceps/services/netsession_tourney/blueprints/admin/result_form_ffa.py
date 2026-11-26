"""
byceps.services.netsession_tourney.blueprints.admin.result_form_ffa
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

FFA parts of the admin result forms (see `result_helpers`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.blueprints.admin.result_form_helpers import (
    _build_ranking,
    _build_score,
)
from byceps.util.result import Err, Ok, Result


# FFA


def parse_ffa_slot_entries(
    request_form, occupied_slots
) -> Result[tuple[dict[int, int], dict[int, int]], str]:
    placements_by_slot_no: dict[int, int] = {}
    kills_by_slot_no: dict[int, int] = {}
    for slot in occupied_slots:
        entry_result = _parse_ffa_slot_entry(request_form, slot.slot_no)
        if entry_result.is_err():
            return Err(entry_result.unwrap_err())

        placement, kills = entry_result.unwrap()
        placements_by_slot_no[slot.slot_no] = placement
        kills_by_slot_no[slot.slot_no] = kills

    return Ok((placements_by_slot_no, kills_by_slot_no))


def _parse_ffa_slot_entry(
    request_form, slot_no: int
) -> Result[tuple[int, int], str]:
    placement_result = _parse_ffa_placement(
        request_form.get(f'placement_slot_{slot_no}')
    )
    if placement_result.is_err():
        return Err(placement_result.unwrap_err())

    kills_result = _parse_ffa_kills(request_form.get(f'kills_slot_{slot_no}'))
    if kills_result.is_err():
        return Err(kills_result.unwrap_err())

    return Ok((placement_result.unwrap(), kills_result.unwrap()))


def _parse_ffa_placement(raw_value: str | None) -> Result[int, str]:
    raw_placement = (raw_value or '').strip()
    if not raw_placement:
        return Err(
            gettext(
                'Bitte für jeden belegten Slot einen Ingame-Platz eintragen.'
            )
        )
    try:
        placement = int(raw_placement)
    except ValueError:
        return Err(
            gettext('Ingame-Plätze müssen als ganze Zahl eingetragen werden.')
        )
    if placement < 1 or placement > 999:
        return Err(gettext('Ingame-Plätze müssen zwischen 1 und 999 liegen.'))

    return Ok(placement)


def _parse_ffa_kills(raw_value: str | None) -> Result[int, str]:
    raw_kills = (raw_value or '').strip()
    if not raw_kills:
        return Err(
            gettext('Bitte für jeden belegten Slot eine Kill-Zahl eintragen.')
        )
    try:
        kills = int(raw_kills)
    except ValueError:
        return Err(gettext('Kills müssen als ganze Zahl eingetragen werden.'))
    if kills < 0 or kills > 999:
        return Err(gettext('Kills müssen zwischen 0 und 999 liegen.'))

    return Ok(kills)


def get_ffa_winner_slot(
    placements_by_slot_no: dict[int, int],
) -> Result[int, str]:
    if len(set(placements_by_slot_no.values())) != len(placements_by_slot_no):
        return Err(
            gettext(
                'Jeder belegte Slot braucht einen eindeutigen Ingame-Platz.'
            )
        )

    winner_slots = [
        slot_no
        for slot_no, placement in placements_by_slot_no.items()
        if placement == 1
    ]
    if len(winner_slots) != 1:
        return Err(
            gettext('Genau ein belegter Slot muss den Ingame-Platz 1 erhalten.')
        )

    return Ok(winner_slots[0])


def build_ffa_score_and_ranking(
    placements_by_slot_no: dict[int, int],
    kills_by_slot_no: dict[int, int],
    placement_points_rules,
) -> tuple[dict, dict]:
    points_by_slot_no = {
        slot_no: _get_ffa_points_for_placement(
            placement_points_rules, placement
        )
        for slot_no, placement in placements_by_slot_no.items()
    }

    score = _build_score(kills_by_slot_no, 'kills')
    ranking = _build_ranking(
        'placement_points', placements_by_slot_no, points_by_slot_no
    )
    return score, ranking


def _get_ffa_points_for_placement(
    placement_points_rules, placement: int | None
) -> int:
    if placement is None or not isinstance(placement_points_rules, list):
        return 0

    for rule in placement_points_rules:
        points = _get_rule_points_for_placement(rule, placement)
        if points is not None:
            return points

    return 0


def _get_rule_points_for_placement(rule, placement: int) -> int | None:
    if not isinstance(rule, dict):
        return None

    try:
        from_place = int(rule.get('from_place'))
        to_place = int(rule.get('to_place'))
        points = int(rule.get('points'))
    except TypeError, ValueError:
        return None

    if from_place <= placement <= to_place:
        return points

    return None

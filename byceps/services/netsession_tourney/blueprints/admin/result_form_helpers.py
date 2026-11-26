"""
byceps.services.netsession_tourney.blueprints.admin.result_form_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Parts of the admin FFA and FlatOut 2 result forms (see `result_helpers`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.util.result import Err, Ok, Result


def get_occupied_slots(slots) -> list:
    return [slot for slot in slots if slot.participant_id is not None]


def parse_result_comment(request_form) -> str | None:
    return (request_form.get('comment') or '').strip() or None


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


# FlatOut 2


def parse_flatout2_slot_points(
    request_form, occupied_slots
) -> Result[dict[int, int], str]:
    points_by_slot_no: dict[int, int] = {}
    for slot in occupied_slots:
        points_result = _parse_flatout2_points(
            request_form.get(f'points_slot_{slot.slot_no}')
        )
        if points_result.is_err():
            return Err(points_result.unwrap_err())

        points_by_slot_no[slot.slot_no] = points_result.unwrap()

    return Ok(points_by_slot_no)


def _parse_flatout2_points(raw_value: str | None) -> Result[int, str]:
    raw_points = (raw_value or '').strip()
    if not raw_points:
        return Err(gettext('Bitte für jeden belegten Slot Punkte eintragen.'))
    try:
        points = int(raw_points)
    except ValueError:
        return Err(gettext('Punkte müssen als ganze Zahl eingetragen werden.'))
    if points < 0 or points > 9999:
        return Err(gettext('Punkte müssen zwischen 0 und 9999 liegen.'))

    return Ok(points)


def get_flatout2_winner_slot(
    points_by_slot_no: dict[int, int],
) -> Result[int, str]:
    max_points = max(points_by_slot_no.values())
    winner_slots = [
        slot_no
        for slot_no, points in points_by_slot_no.items()
        if points == max_points
    ]
    if len(winner_slots) != 1:
        return Err(gettext('Der höchste Punktestand muss eindeutig sein.'))

    return Ok(winner_slots[0])


def build_flatout2_score_and_ranking(
    points_by_slot_no: dict[int, int],
) -> tuple[dict, dict]:
    ordered_slot_nos = sorted(
        points_by_slot_no.keys(),
        key=lambda slot_no: (-points_by_slot_no[slot_no], slot_no),
    )
    placements_by_slot_no = {
        slot_no: index
        for index, slot_no in enumerate(ordered_slot_nos, start=1)
    }

    score = _build_score(points_by_slot_no, 'points')
    ranking = _build_ranking('points', placements_by_slot_no, points_by_slot_no)
    return score, ranking


# shared


def _build_score(values_by_slot_no: dict[int, int], metric: str) -> dict:
    return {
        'display': gettext('Erfasst'),
        'slots': {
            str(slot_no): value
            for slot_no, value in sorted(values_by_slot_no.items())
        },
        'metric': metric,
    }


def _build_ranking(
    metric: str,
    placements_by_slot_no: dict[int, int],
    points_by_slot_no: dict[int, int],
) -> dict:
    return {
        'metric': metric,
        'placements': {
            str(slot_no): placement
            for slot_no, placement in sorted(placements_by_slot_no.items())
        },
        'points': {
            str(slot_no): points
            for slot_no, points in sorted(points_by_slot_no.items())
        },
    }

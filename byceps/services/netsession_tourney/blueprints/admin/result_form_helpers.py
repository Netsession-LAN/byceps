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

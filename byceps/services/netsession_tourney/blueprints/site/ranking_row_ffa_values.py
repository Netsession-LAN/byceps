"""
byceps.services.netsession_tourney.blueprints.site.ranking_row_ffa_values
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Parse the per slot values (placement, kills, points) of an FFA result.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations


def _get_raw_slot_value(raw_values: dict, slot):
    raw_value = raw_values.get(str(slot.slot_no))
    if raw_value is None:
        raw_value = raw_values.get(slot.slot_no)
    return raw_value


def _parse_int_values_by_slot_no(raw_values, slots) -> dict[int, int]:
    values_by_slot_no = {}
    if not isinstance(raw_values, dict):
        return values_by_slot_no

    for slot in slots:
        raw_value = _get_raw_slot_value(raw_values, slot)
        try:
            values_by_slot_no[slot.slot_no] = int(raw_value)
        except TypeError, ValueError:
            continue

    return values_by_slot_no


def _parse_ffa_ranking_values(result, slots) -> tuple[dict, dict]:
    if not isinstance(result.ranking, dict):
        return {}, {}

    placement_by_slot_no = _parse_int_values_by_slot_no(
        result.ranking.get('placements'), slots
    )
    points_by_slot_no = _parse_int_values_by_slot_no(
        result.ranking.get('points'), slots
    )
    return placement_by_slot_no, points_by_slot_no

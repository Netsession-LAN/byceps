"""
byceps.services.netsession_tourney.score_parsing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Reading scores, results and FFA points from stored JSON.
"""

from __future__ import annotations

from typing import Any

from .dbmodels import (
    DbNetsessionTourneyMatchSlot,
)


def parse_numeric_score_value(value: Any) -> int:
    if value is None:
        return 0

    try:
        return int(str(value).strip())
    except TypeError, ValueError:
        return 0


def is_walkover_score_json(score_json: dict[str, Any] | None) -> bool:
    if not isinstance(score_json, dict):
        return False

    return bool(score_json.get('walkover'))


def parse_match_result_slot_scores(
    slots: list[DbNetsessionTourneyMatchSlot],
    score_json: dict[str, Any] | None,
    *,
    winner_slot: int | None,
) -> dict[int, str]:
    if not slots or not isinstance(score_json, dict):
        return {}

    raw_slots = score_json.get('slots')
    if isinstance(raw_slots, dict):
        parsed_scores = {}
        for slot in slots:
            raw_value = raw_slots.get(str(slot.slot_no))
            if raw_value is None:
                raw_value = raw_slots.get(slot.slot_no)
            if raw_value is None:
                continue

            normalized = str(raw_value).strip()
            if not normalized:
                continue

            parsed_scores[slot.slot_no] = normalized

        if parsed_scores:
            return parsed_scores

    raw_display = score_json.get('display')
    if isinstance(raw_display, str):
        display = raw_display.strip().replace(' ', '')
        if display:
            delimiter = next(
                (
                    candidate
                    for candidate in [':', '-', '/']
                    if candidate in display
                ),
                None,
            )
            if delimiter is not None:
                parts = display.split(delimiter)
                if len(parts) == len(slots) and all(
                    part.isdigit() for part in parts
                ):
                    normalized_parts = list(parts)
                    if len(slots) == 2 and winner_slot is not None:
                        left = int(parts[0])
                        right = int(parts[1])
                        if left != right:
                            first_slot_no = slots[0].slot_no
                            second_slot_no = slots[1].slot_no
                            winner_has_lower_score = (
                                winner_slot == first_slot_no and left < right
                            ) or (
                                winner_slot == second_slot_no and right < left
                            )
                            if winner_has_lower_score:
                                normalized_parts = [parts[1], parts[0]]

                    return {
                        slot.slot_no: normalized_parts[index]
                        for index, slot in enumerate(slots)
                    }

    if winner_slot is None or len(slots) != 2:
        return {}

    return {
        slots[0].slot_no: '1' if winner_slot == slots[0].slot_no else '0',
        slots[1].slot_no: '1' if winner_slot == slots[1].slot_no else '0',
    }


def get_ffa_points_per_kill(settings: dict[str, Any] | None) -> int:
    if not isinstance(settings, dict):
        return 1

    raw_value = settings.get('points_per_kill', 1)
    try:
        value = int(raw_value)
    except TypeError, ValueError:
        return 1

    return max(0, value)

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

    parsed_scores = _parse_slot_scores_by_slot_no(
        slots, score_json.get('slots')
    )
    if parsed_scores:
        return parsed_scores

    display_scores = _parse_slot_scores_from_display(
        slots, score_json.get('display'), winner_slot
    )
    if display_scores is not None:
        return display_scores

    return _build_winner_only_slot_scores(slots, winner_slot)


def _parse_slot_scores_by_slot_no(
    slots: list[DbNetsessionTourneyMatchSlot], raw_slots: Any
) -> dict[int, str]:
    """Return the non-empty scores stored per slot number."""
    if not isinstance(raw_slots, dict):
        return {}

    parsed_scores = {}
    for slot in slots:
        normalized = _get_stored_slot_score(raw_slots, slot.slot_no)
        if normalized:
            parsed_scores[slot.slot_no] = normalized

    return parsed_scores


def _get_stored_slot_score(
    raw_slots: dict[Any, Any], slot_no: int
) -> str | None:
    raw_value = raw_slots.get(str(slot_no))
    if raw_value is None:
        raw_value = raw_slots.get(slot_no)
    if raw_value is None:
        return None

    return str(raw_value).strip()


def _parse_slot_scores_from_display(
    slots: list[DbNetsessionTourneyMatchSlot],
    raw_display: Any,
    winner_slot: int | None,
) -> dict[int, str] | None:
    """Return the scores of a display string like `16:9`, or `None` if
    there is no usable one."""
    parts = _split_display_score(raw_display, len(slots))
    if parts is None:
        return None

    normalized_parts = _order_display_score_parts(parts, slots, winner_slot)
    return {
        slot.slot_no: normalized_parts[index]
        for index, slot in enumerate(slots)
    }


def _split_display_score(raw_display: Any, slot_count: int) -> list[str] | None:
    if not isinstance(raw_display, str):
        return None

    display = raw_display.strip().replace(' ', '')
    if not display:
        return None

    delimiter = _find_display_score_delimiter(display)
    if delimiter is None:
        return None

    parts = display.split(delimiter)
    if not _are_digit_parts_per_slot(parts, slot_count):
        return None

    return parts


def _find_display_score_delimiter(display: str) -> str | None:
    return next(
        (candidate for candidate in [':', '-', '/'] if candidate in display),
        None,
    )


def _are_digit_parts_per_slot(parts: list[str], slot_count: int) -> bool:
    return len(parts) == slot_count and all(part.isdigit() for part in parts)


def _order_display_score_parts(
    parts: list[str],
    slots: list[DbNetsessionTourneyMatchSlot],
    winner_slot: int | None,
) -> list[str]:
    """Swap the two scores if the winner would otherwise have the lower
    one."""
    normalized_parts = list(parts)
    if len(slots) != 2 or winner_slot is None:
        return normalized_parts

    left = int(parts[0])
    right = int(parts[1])
    if left != right and _winner_has_lower_score(
        winner_slot, slots[0].slot_no, slots[1].slot_no, left, right
    ):
        return [parts[1], parts[0]]

    return normalized_parts


def _winner_has_lower_score(
    winner_slot: int,
    first_slot_no: int,
    second_slot_no: int,
    left: int,
    right: int,
) -> bool:
    return (winner_slot == first_slot_no and left < right) or (
        winner_slot == second_slot_no and right < left
    )


def _build_winner_only_slot_scores(
    slots: list[DbNetsessionTourneyMatchSlot], winner_slot: int | None
) -> dict[int, str]:
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

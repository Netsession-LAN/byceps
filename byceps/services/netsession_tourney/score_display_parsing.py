"""
byceps.services.netsession_tourney.score_display_parsing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Reading slot scores from the stored display string of a match result.
"""

from __future__ import annotations

from typing import Any

from .dbmodels import (
    DbNetsessionTourneyMatchSlot,
)


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

"""
byceps.services.netsession_tourney.blueprints.site.match_score_display
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Slot scores from the display score of a result ("3:1").

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations


def _get_normalized_score_display(result) -> str:
    if not result.score:
        return ''

    raw_display = result.score.get('display')
    if not isinstance(raw_display, str):
        return ''

    return raw_display.strip().replace(' ', '')


def _find_score_display_delimiter(display: str) -> str | None:
    for candidate in [':', '-', '/']:
        if candidate in display:
            return candidate
    return None


def _split_score_display(display: str, slot_count: int) -> list[str] | None:
    delimiter = _find_score_display_delimiter(display)
    if delimiter is None:
        return None

    parts = display.split(delimiter)
    if len(parts) != slot_count or not all(part.isdigit() for part in parts):
        return None

    return parts


def _winner_has_lower_score(winner_slot, slots, left: int, right: int) -> bool:
    return (winner_slot == slots[0].slot_no and left < right) or (
        winner_slot == slots[1].slot_no and right < left
    )


def _align_score_parts_with_winner(slots, result, parts: list[str]) -> list:
    # Keep display aligned with winner slot if a reversed score
    # string was submitted (e.g. winner_slot=1 with "0:1").
    if len(slots) != 2 or result.winner_slot is None:
        return list(parts)

    left = int(parts[0])
    right = int(parts[1])
    if left == right:
        return list(parts)

    if _winner_has_lower_score(result.winner_slot, slots, left, right):
        return [parts[1], parts[0]]

    return list(parts)


def _parse_display_slot_scores(slots, result) -> dict[int, str] | None:
    display = _get_normalized_score_display(result)
    if not display:
        return None

    parts = _split_score_display(display, len(slots))
    if parts is None:
        return None

    normalized_parts = _align_score_parts_with_winner(slots, result, parts)
    return {
        slot.slot_no: normalized_parts[index]
        for index, slot in enumerate(slots)
    }

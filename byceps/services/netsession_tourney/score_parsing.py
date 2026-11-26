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
from .score_display_parsing import (
    _parse_slot_scores_from_display,
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

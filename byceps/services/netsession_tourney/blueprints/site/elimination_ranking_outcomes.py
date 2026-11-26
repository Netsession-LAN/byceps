"""
byceps.services.netsession_tourney.blueprints.site.elimination_ranking_outcomes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Match outcomes for the elimination placements: who won, who lost,
who was eliminated, and whether the bracket is finished.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .match_grand_final_skips import is_skipped_double_grand_final_result


ParticipantId = Any


def _played_matches(matches, results_by_match_id) -> list:
    return [
        match
        for match in matches
        if not is_skipped_double_grand_final_result(
            results_by_match_id.get(match.id)
        )
    ]


def _is_bracket_finished(played, final_id, slots_by_match_id, results) -> bool:
    for match in played:
        if _is_real_match(match, slots_by_match_id) and (
            _outcome(match, slots_by_match_id, results) is None
        ):
            return False
    final_match = next(m for m in played if m.id == final_id)
    return _outcome(final_match, slots_by_match_id, results) is not None


def _eliminated_groups(
    played, targets, distance, placed_match_ids, slots_by_match_id, results
) -> list[list[ParticipantId]]:
    eliminated_by_distance: dict[int, list[ParticipantId]] = defaultdict(list)
    for match in played:
        if match.id in placed_match_ids:
            continue
        if _loser_drops_into_another_match(targets, match):
            continue  # loser drops into another match, not eliminated here
        outcome = _outcome(match, slots_by_match_id, results)
        if outcome is not None and outcome[1] is not None:
            eliminated_by_distance[distance.get(match.id, 999)].append(
                outcome[1]
            )
    return [
        eliminated_by_distance[key] for key in sorted(eliminated_by_distance)
    ]


def _loser_drops_into_another_match(targets, match) -> bool:
    return any(outcome == 'loser' for _, outcome in targets[match.id])


def _participants(slots_by_match_id, match_id) -> list[ParticipantId]:
    return [
        slot.participant_id
        for slot in slots_by_match_id.get(match_id, [])
        if slot.participant_id is not None
    ]


def _is_real_match(match, slots_by_match_id) -> bool:
    """Two participants, i.e. not a bye."""
    return len(_participants(slots_by_match_id, match.id)) >= 2


def _outcome(match, slots_by_match_id, results):
    """Return (winner, loser) of a decided match, loser `None` for byes."""
    slots = slots_by_match_id.get(match.id, [])
    result = results.get(match.id)
    if result is None or result.winner_slot is None:
        return _undecided_outcome(match, slots_by_match_id)
    return _find_winner_and_loser(slots, result)


def _undecided_outcome(match, slots_by_match_id):
    if not _is_real_match(match, slots_by_match_id):
        participants = _participants(slots_by_match_id, match.id)
        return (participants[0], None) if participants else None
    return None


def _find_winner_and_loser(slots, result):
    winner = loser = None
    for slot in slots:
        if result is not None and slot.slot_no == result.winner_slot:
            winner = slot.participant_id
        elif slot.participant_id is not None:
            loser = slot.participant_id
    return winner, loser


def _winner_and_loser_groups(match_id, slots_by_match_id, results):
    slots = slots_by_match_id.get(match_id, [])
    result = results.get(match_id)
    winner, loser = _find_winner_and_loser(slots, result)
    return [[p] for p in (winner, loser) if p is not None]

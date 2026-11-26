"""
byceps.services.netsession_tourney.blueprints.site.elimination_ranking_structure
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Bracket structure for the elimination placements: where winners and
losers go, the final, the third-place match and distances to the final.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


MatchId = Any


def _build_targets(matches, slots_by_match_id):
    """Map match ID -> set of (target match ID, 'winner'|'loser')."""
    match_id_by_slot_id = {
        slot.id: match.id
        for match in matches
        for slot in slots_by_match_id.get(match.id, [])
    }
    targets: dict[MatchId, set] = {match.id: set() for match in matches}
    for match in matches:
        for slot in slots_by_match_id.get(match.id, []):
            source_match_id = match_id_by_slot_id.get(slot.source_match_slot_id)
            if source_match_id is not None:
                targets[source_match_id].add(
                    (match.id, _outcome_value(slot.source_outcome))
                )
    return targets


def _outcome_value(source_outcome) -> str:
    return getattr(source_outcome, 'value', source_outcome)


def _incoming_outcomes(match, slots_by_match_id) -> set[str]:
    return {
        _outcome_value(slot.source_outcome)
        for slot in slots_by_match_id.get(match.id, [])
        if slot.source_match_slot_id is not None
    }


def _find_final_and_third_place(matches, targets, slots_by_match_id):
    third_place, finals = _split_terminal_matches(
        matches, targets, slots_by_match_id
    )
    if len(finals) != 1:
        return None, None
    third_place_id = third_place[0].id if len(third_place) == 1 else None
    return finals[0].id, third_place_id


def _split_terminal_matches(matches, targets, slots_by_match_id):
    terminal = [m for m in matches if not targets[m.id]]
    third_place = [
        m for m in terminal if _is_third_place_match(m, slots_by_match_id)
    ]
    finals = [m for m in terminal if m not in third_place]
    return third_place, finals


def _is_third_place_match(match, slots_by_match_id) -> bool:
    return _incoming_outcomes(match, slots_by_match_id) == {'loser'}


def _distances_to_final(matches, targets, final_id) -> dict[MatchId, int]:
    """Number of wins still needed to reach the final (shortest path)."""
    sources: dict[MatchId, set] = defaultdict(set)
    for match_id, edges in targets.items():
        for target_id, outcome in edges:
            if outcome == 'winner':
                sources[target_id].add(match_id)
    distance = {final_id: 0}
    queue = [final_id]
    while queue:
        current = queue.pop(0)
        for source in sources[current]:
            if source not in distance:
                distance[source] = distance[current] + 1
                queue.append(source)
    return distance

"""
byceps.services.netsession_tourney.blueprints.site.elimination_ranking
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Final placements for elimination brackets (single, double, double with
grand final reset), derived from how matches feed into each other.

- Winner of the final is 1st, its loser 2nd.
- A third-place match (fed only by losers, feeding nothing) ranks its
  winner and loser next.
- Everybody else is ranked by how close to the final they were
  eliminated; participants eliminated equally close share a place.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from .match_helpers import is_skipped_double_grand_final_result


ParticipantId = Any
MatchId = Any


def build_elimination_placements(
    matches: Iterable[Any],
    slots_by_match_id: dict[MatchId, list[Any]],
    results_by_match_id: dict[MatchId, Any],
) -> dict[ParticipantId, int] | None:
    """Return a place per participant, or `None` if the bracket is not
    finished or has no single final."""
    # A skipped grand final reset is treated as if it did not exist.
    played = _played_matches(matches, results_by_match_id)
    results = {match.id: results_by_match_id.get(match.id) for match in played}
    if not played:
        return None

    targets = _build_targets(played, slots_by_match_id)
    final_id, third_place_id = _find_final_and_third_place(
        played, targets, slots_by_match_id
    )
    if final_id is None:
        return None

    # Only rank a finished bracket: every real match must be decided.
    if not _is_bracket_finished(played, final_id, slots_by_match_id, results):
        return None

    distance = _distances_to_final(played, targets, final_id)
    groups: list[list[ParticipantId]] = []
    groups += _winner_and_loser_groups(final_id, slots_by_match_id, results)
    if third_place_id is not None:
        groups += _winner_and_loser_groups(
            third_place_id, slots_by_match_id, results
        )

    groups += _eliminated_groups(
        played,
        targets,
        distance,
        {final_id, third_place_id},
        slots_by_match_id,
        results,
    )

    return _places_from_groups(groups)


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


def _winner_and_loser_groups(match_id, slots_by_match_id, results):
    slots = slots_by_match_id.get(match_id, [])
    result = results.get(match_id)
    winner, loser = _find_winner_and_loser(slots, result)
    return [[p] for p in (winner, loser) if p is not None]


def _places_from_groups(groups) -> dict[ParticipantId, int]:
    places: dict[ParticipantId, int] = {}
    next_place = 1
    for group in groups:
        group = [p for p in group if p not in places]
        for participant_id in group:
            places[participant_id] = next_place
        next_place += len(group)
    return places


def apply_placements(ranking_rows: list[dict], places) -> list[dict]:
    """Order ranking rows by place; participants without a place follow."""
    placed = sorted(
        (row for row in ranking_rows if row['participant'].id in places),
        key=lambda row: places[row['participant'].id],
    )
    rest = [row for row in ranking_rows if row['participant'].id not in places]
    rows = [{**row, 'rank': places[row['participant'].id]} for row in placed]
    _append_unplaced_rows(rows, rest)
    return rows


def _append_unplaced_rows(rows: list[dict], rest: list[dict]) -> None:
    next_rank = len(rows) + 1
    previous_rank = None
    for index, row in enumerate(rest):
        if row.get('rank') != previous_rank:
            current = next_rank + index
            previous_rank = row.get('rank')
        rows.append({**row, 'rank': current})


ELIMINATION_STAGE_TYPE_VALUES = {
    'single_elimination',
    'double_elimination',
    'double_elimination_double_grand_final',
}


def rank_by_elimination(
    ranking_rows: list[dict],
    stages,
    matches,
    slots_by_match_id,
    results_by_match_id,
) -> list[dict]:
    """If the last stage is a finished elimination bracket, order the
    ranking by bracket placement; otherwise return the rows unchanged."""
    if not ranking_rows or not stages:
        return ranking_rows
    last_stage = max(stages, key=lambda stage: stage.order_no)
    if _outcome_value(last_stage.type) not in ELIMINATION_STAGE_TYPE_VALUES:
        return ranking_rows
    stage_matches = [m for m in matches if m.stage_id == last_stage.id]
    places = build_elimination_placements(
        stage_matches, slots_by_match_id, results_by_match_id
    )
    if not places:
        return ranking_rows
    return apply_placements(ranking_rows, places)

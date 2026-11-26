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

from collections.abc import Iterable
from typing import Any

from .elimination_ranking_outcomes import (
    _eliminated_groups,
    _is_bracket_finished,
    _played_matches,
    _winner_and_loser_groups,
    ParticipantId,
)
from .elimination_ranking_structure import (
    _build_targets,
    _distances_to_final,
    _find_final_and_third_place,
    _outcome_value,
    MatchId,
)


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

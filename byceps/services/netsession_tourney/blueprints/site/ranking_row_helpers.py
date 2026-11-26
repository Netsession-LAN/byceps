"""
byceps.services.netsession_tourney.blueprints.site.ranking_row_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Building blocks for the FFA and FlatOut 2 ranking rows in
`ranking_helpers`.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.score_parsing import (
    get_ffa_points_per_kill,
)

from .match_helpers import _parse_slot_scores
from .ranking_row_ffa_values import _parse_ffa_ranking_values


UNKNOWN_PLACEMENT = 999999


# -------------------------------------------------------------------- #
# shared


def _placement_sort_value(placement) -> int:
    return placement if placement is not None else UNKNOWN_PLACEMENT


def participant_sort_values(row) -> tuple:
    return (
        row['participant'].seed or UNKNOWN_PLACEMENT,
        row['participant'].name.lower(),
    )


def has_played_rows(rows_by_participant_id) -> bool:
    return any(row['played'] for row in rows_by_participant_id.values())


def assign_shared_ranks(rows, get_sort_value) -> list[dict]:
    ranking_rows = []
    rank = 0
    last_sort_value = None
    for index, row in enumerate(rows, start=1):
        sort_value = get_sort_value(row)
        if sort_value != last_sort_value:
            rank = index
            last_sort_value = sort_value
        ranking_rows.append({'rank': rank, **row})

    return ranking_rows


def _iter_participant_rows(slots, rows_by_participant_id):
    for slot in slots:
        if slot.participant_id is None:
            continue

        row = rows_by_participant_id.get(slot.participant_id)
        if row is None:
            continue

        yield slot, row


def _keep_best_placement(row, key: str, placement) -> None:
    if placement is None:
        return

    if row[key] is None or placement < row[key]:
        row[key] = placement


# -------------------------------------------------------------------- #
# FFA


def new_ffa_ranking_row(participant) -> dict:
    return {
        'participant': participant,
        'total_points': 0,
        'points': 0,
        'wins': 0,
        'played': 0,
        'kills': 0,
        'placement': None,
    }


def _add_ffa_kills(row, slot_scores, slot_no: int) -> None:
    try:
        row['kills'] += int(slot_scores.get(slot_no, '0'))
    except ValueError:
        pass


def _apply_ffa_slot_result(
    row,
    slot,
    result,
    slot_scores,
    placement_by_slot_no,
    points_by_slot_no,
    points_per_kill,
) -> None:
    row['played'] += 1
    row['points'] += points_by_slot_no.get(slot.slot_no, 0)
    if result.winner_slot == slot.slot_no:
        row['wins'] += 1

    _add_ffa_kills(row, slot_scores, slot.slot_no)

    row['total_points'] = row['points'] + (row['kills'] * points_per_kill)

    _keep_best_placement(
        row, 'placement', placement_by_slot_no.get(slot.slot_no)
    )


def apply_ffa_match(
    rows_by_participant_id,
    match,
    slots_by_match_id,
    results_by_match_id,
    stages_by_id,
) -> None:
    result = results_by_match_id.get(match.id)
    if result is None:
        return

    stage = stages_by_id.get(match.stage_id)
    points_per_kill = get_ffa_points_per_kill(
        stage.settings if stage is not None else None
    )
    slots = slots_by_match_id.get(match.id, [])
    placement_by_slot_no, points_by_slot_no = _parse_ffa_ranking_values(
        result, slots
    )

    slot_scores = _parse_slot_scores(slots, result)
    for slot, row in _iter_participant_rows(slots, rows_by_participant_id):
        _apply_ffa_slot_result(
            row,
            slot,
            result,
            slot_scores,
            placement_by_slot_no,
            points_by_slot_no,
            points_per_kill,
        )


def ffa_ranking_sort_key(row) -> tuple:
    return (
        -row['total_points'],
        -row['points'],
        -row['kills'],
        _placement_sort_value(row['placement']),
        *participant_sort_values(row),
    )


def ffa_ranking_tie_value(row) -> tuple:
    return (
        row['total_points'],
        row['points'],
        row['kills'],
        _placement_sort_value(row['placement']),
    )


# -------------------------------------------------------------------- #
# FlatOut 2


def new_flatout2_ranking_row(participant) -> dict:
    return {
        'participant': participant,
        'wins': 0,
        'played': 0,
        'best_placement': None,
    }


def apply_flatout2_match(
    rows_by_participant_id,
    match,
    slots_by_match_id,
    results_by_match_id,
    get_ffa_placement_by_slot_no,
) -> None:
    result = results_by_match_id.get(match.id)
    if result is None:
        return

    slots = slots_by_match_id.get(match.id, [])
    placement_by_slot_no = get_ffa_placement_by_slot_no(result, slots)
    for slot, row in _iter_participant_rows(slots, rows_by_participant_id):
        row['played'] += 1
        if result.winner_slot == slot.slot_no:
            row['wins'] += 1

        _keep_best_placement(
            row, 'best_placement', placement_by_slot_no.get(slot.slot_no)
        )


def flatout2_ranking_sort_key(row) -> tuple:
    return (
        -row['wins'],
        _placement_sort_value(row['best_placement']),
        *participant_sort_values(row),
    )


def flatout2_ranking_tie_value(row) -> tuple:
    return (
        row['wins'],
        _placement_sort_value(row['best_placement']),
    )

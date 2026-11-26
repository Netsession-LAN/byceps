"""
byceps.services.netsession_tourney.blueprints.site.ranking_duel_standings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Opponent strengths, Swiss and points ranking rows from the duel
ranking state.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict

from .ranking_duel_state import (
    DuelRankingState,
)
from .ranking_row_helpers import assign_shared_ranks, participant_sort_values


def _get_opponent_ids(opponent_ids_by_participant_id, participant_id) -> list:
    return opponent_ids_by_participant_id.get(participant_id, [])


def _sum_opponent_stat(stats_by_participant_id, opponent_ids, key: str) -> int:
    return sum(
        stats_by_participant_id.get(opponent_id, {}).get(key, 0)
        for opponent_id in opponent_ids
    )


def _sum_opponent_win_loss_diff(stats_by_participant_id, opponent_ids) -> int:
    return sum(
        stats_by_participant_id.get(opponent_id, {}).get('wins', 0)
        - stats_by_participant_id.get(opponent_id, {}).get('losses', 0)
        for opponent_id in opponent_ids
    )


def apply_opponent_strengths(duel_state: DuelRankingState) -> None:
    stats_by_participant_id = duel_state.stats_by_participant_id
    opponents = duel_state.opponent_ids_by_participant_id

    for participant_id, row in stats_by_participant_id.items():
        opponent_ids = _get_opponent_ids(opponents, participant_id)
        row['buchholz'] = _sum_opponent_stat(
            stats_by_participant_id, opponent_ids, 'wins'
        )
        row['opponent_wl_sum'] = _sum_opponent_win_loss_diff(
            stats_by_participant_id, opponent_ids
        )
    for participant_id, row in stats_by_participant_id.items():
        opponent_ids = _get_opponent_ids(opponents, participant_id)
        row['second_order_sos'] = _sum_opponent_stat(
            stats_by_participant_id, opponent_ids, 'opponent_wl_sum'
        )


def _build_swiss_head_to_head_scores(rows, head_to_head_winner_id_by_pair):
    scores_by_participant_id = {row['participant'].id: 0 for row in rows}
    participant_ids_by_base_tie_values = defaultdict(list)
    for row in rows:
        participant_ids_by_base_tie_values[
            (
                row['wins'],
                row['losses'],
                row['buchholz'],
                row.get('opponent_wl_sum', 0),
                row.get('second_order_sos', 0),
            )
        ].append(row['participant'].id)

    for participant_ids in participant_ids_by_base_tie_values.values():
        if len(participant_ids) != 2:
            continue

        winner_id = head_to_head_winner_id_by_pair.get(
            frozenset(participant_ids)
        )
        if winner_id in scores_by_participant_id:
            scores_by_participant_id[winner_id] = 1

    return scores_by_participant_id


def _swiss_ranking_sort_key(row, swiss_head_to_head_scores) -> tuple:
    return (
        -row['wins'],
        row['losses'],
        -row['buchholz'],
        -row['opponent_wl_sum'],
        -row['second_order_sos'],
        -swiss_head_to_head_scores.get(row['participant'].id, 0),
        -row['round_diff'],
        -row['round_wins'],
        *participant_sort_values(row),
    )


def build_swiss_ranking_rows(
    rows, head_to_head_winner_id_by_pair
) -> list[dict]:
    swiss_head_to_head_scores = _build_swiss_head_to_head_scores(
        rows, head_to_head_winner_id_by_pair
    )
    rows = sorted(
        rows,
        key=lambda row: _swiss_ranking_sort_key(row, swiss_head_to_head_scores),
    )

    return [{'rank': index, **row} for index, row in enumerate(rows, start=1)]


def _build_direct_compare_scores(
    participant_ids, head_to_head_winner_id_by_pair
) -> dict:
    direct_compare_scores = {
        participant_id: 0 for participant_id in participant_ids
    }
    if len(participant_ids) == 2:
        winner_id = head_to_head_winner_id_by_pair.get(
            frozenset(participant_ids)
        )
        if winner_id in direct_compare_scores:
            direct_compare_scores[winner_id] = 1

    return direct_compare_scores


def _build_tie_break_values_by_participant_id(
    rows, duel_state: DuelRankingState
) -> dict:
    participant_ids_by_match_points = defaultdict(list)
    for row in rows:
        participant_ids_by_match_points[row['match_points']].append(
            row['participant'].id
        )

    tie_break_values_by_participant_id = {}
    for participant_ids in participant_ids_by_match_points.values():
        direct_compare_scores = _build_direct_compare_scores(
            participant_ids, duel_state.head_to_head_winner_id_by_pair
        )
        for participant_id in participant_ids:
            row = duel_state.stats_by_participant_id[participant_id]
            tie_break_values_by_participant_id[participant_id] = (
                row['match_points'],
                direct_compare_scores[participant_id],
                row['round_diff'],
                row['round_wins'],
            )

    return tie_break_values_by_participant_id


def build_points_ranking_rows(rows, duel_state: DuelRankingState) -> list[dict]:
    tie_break_values_by_participant_id = (
        _build_tie_break_values_by_participant_id(rows, duel_state)
    )

    def get_tie_break_values(row) -> tuple:
        return tie_break_values_by_participant_id[row['participant'].id]

    rows = sorted(
        rows,
        key=lambda row: (
            -get_tie_break_values(row)[0],
            -get_tie_break_values(row)[1],
            -get_tie_break_values(row)[2],
            -get_tie_break_values(row)[3],
            *participant_sort_values(row),
        ),
    )

    return assign_shared_ranks(rows, get_tie_break_values)

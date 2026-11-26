"""
byceps.services.netsession_tourney.blueprints.site.ranking_duel_row_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Building blocks for the duel ranking rows (round robin, league, Swiss,
elimination) in `ranking_helpers`.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict

from byceps.services.netsession_tourney.models import StageType
from byceps.services.netsession_tourney.score_parsing import (
    parse_numeric_score_value,
)

from .match_helpers import (
    _parse_slot_scores,
    is_skipped_double_grand_final_result,
)
from .ranking_row_helpers import assign_shared_ranks, participant_sort_values


def new_duel_stats_row(participant) -> dict:
    return {
        'participant': participant,
        'wins': 0,
        'losses': 0,
        'played': 0,
        'match_points': 0,
        'round_wins': 0,
        'round_losses': 0,
        'round_diff': 0,
        'buchholz': 0,
        'opponent_wl_sum': 0,
        'second_order_sos': 0,
    }


class DuelRankingState:
    def __init__(self, participants) -> None:
        self.stats_by_participant_id = {
            participant.id: new_duel_stats_row(participant)
            for participant in participants
        }
        self.head_to_head_winner_id_by_pair = {}
        self.opponent_ids_by_participant_id = defaultdict(list)


def _is_walkover_result(result) -> bool:
    if result is None or not isinstance(result.score, dict):
        return False

    return bool(result.score.get('walkover'))


def _get_slot_participant_ids(slots) -> list:
    return [
        slot.participant_id for slot in slots if slot.participant_id is not None
    ]


def _find_duel_winner_id(result, slots):
    slot_by_no = {slot.slot_no: slot for slot in slots}
    if result is None or result.winner_slot is None:
        return None

    winner_slot = slot_by_no.get(result.winner_slot)
    return winner_slot.participant_id if winner_slot else None


def _apply_duel_outcome(
    stats_by_participant_id, participant_ids, result, winner_id
) -> None:
    for participant_id in participant_ids:
        row = stats_by_participant_id.get(participant_id)
        if row is None:
            continue
        if result is not None:
            row['played'] += 1
        if winner_id is None:
            continue
        if participant_id == winner_id:
            row['wins'] += 1
            row['match_points'] += 3
        else:
            row['losses'] += 1


def _get_ordered_participant_slots(slots) -> list:
    return [
        slot
        for slot in sorted(slots, key=lambda slot: slot.slot_no)
        if slot.participant_id is not None
    ]


def _record_duel_opponents(
    ordered_slots, opponent_ids_by_participant_id, is_walkover_result: bool
) -> None:
    participant_a_id = ordered_slots[0].participant_id
    participant_b_id = ordered_slots[1].participant_id
    if (
        participant_a_id is not None
        and participant_b_id is not None
        and not is_walkover_result
    ):
        opponent_ids_by_participant_id[participant_a_id].append(
            participant_b_id
        )
        opponent_ids_by_participant_id[participant_b_id].append(
            participant_a_id
        )


def _count_rounds_lost(ordered_slots, slot_scores, slot) -> int:
    return sum(
        parse_numeric_score_value(slot_scores.get(other_slot.slot_no))
        for other_slot in ordered_slots
        if other_slot.slot_no != slot.slot_no
    )


def _apply_round_scores(
    ordered_slots, slot_scores, stats_by_participant_id
) -> None:
    for slot in ordered_slots:
        participant_id = slot.participant_id
        if participant_id is None:
            continue

        rounds_won = parse_numeric_score_value(slot_scores.get(slot.slot_no))
        rounds_lost = _count_rounds_lost(ordered_slots, slot_scores, slot)
        row = stats_by_participant_id.get(participant_id)
        if row is not None:
            row['round_wins'] += rounds_won
            row['round_losses'] += rounds_lost
            row['round_diff'] = row['round_wins'] - row['round_losses']


def _apply_duel_pairing(
    slots,
    slot_scores,
    participant_ids,
    winner_id,
    is_walkover_result: bool,
    duel_state: DuelRankingState,
) -> None:
    ordered_slots = _get_ordered_participant_slots(slots)
    if len(ordered_slots) != 2:
        return

    _record_duel_opponents(
        ordered_slots,
        duel_state.opponent_ids_by_participant_id,
        is_walkover_result,
    )

    if winner_id in participant_ids and not is_walkover_result:
        duel_state.head_to_head_winner_id_by_pair[
            frozenset(participant_ids)
        ] = winner_id

    if is_walkover_result:
        return

    _apply_round_scores(
        ordered_slots, slot_scores, duel_state.stats_by_participant_id
    )


def apply_duel_match(
    duel_state: DuelRankingState,
    match,
    slots_by_match_id,
    results_by_match_id,
    stage_type: StageType | None,
) -> None:
    result = results_by_match_id.get(match.id)
    if is_skipped_double_grand_final_result(result):
        return
    slots = slots_by_match_id.get(match.id, [])
    slot_scores = _parse_slot_scores(slots, result)
    participant_ids = _get_slot_participant_ids(slots)
    if len(participant_ids) < 2:
        return

    winner_id = _find_duel_winner_id(result, slots)
    is_walkover_result = stage_type == StageType.swiss and _is_walkover_result(
        result
    )

    _apply_duel_outcome(
        duel_state.stats_by_participant_id, participant_ids, result, winner_id
    )

    if len(participant_ids) != 2:
        return

    _apply_duel_pairing(
        slots,
        slot_scores,
        participant_ids,
        winner_id,
        is_walkover_result,
        duel_state,
    )


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

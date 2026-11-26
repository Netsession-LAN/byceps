"""
byceps.services.netsession_tourney.blueprints.site.ranking_duel_pairing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Apply the pairing of a played duel (opponents, rounds, head to
head) to the duel ranking state.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.score_parsing import (
    parse_numeric_score_value,
)

from .ranking_duel_state import (
    DuelRankingState,
)


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

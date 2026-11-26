"""
byceps.services.netsession_tourney.blueprints.site.ranking_duel_row_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Building blocks for the duel ranking rows (round robin, league, Swiss,
elimination) in `ranking_helpers`.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.models import StageType

from .match_grand_final_skips import is_skipped_double_grand_final_result
from .match_helpers import _parse_slot_scores
from .ranking_duel_pairing import (
    _apply_duel_pairing,
)
from .ranking_duel_standings import (
    apply_opponent_strengths as apply_opponent_strengths,
    build_points_ranking_rows as build_points_ranking_rows,
    build_swiss_ranking_rows as build_swiss_ranking_rows,
)
from .ranking_duel_state import (
    DuelRankingState,
)


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

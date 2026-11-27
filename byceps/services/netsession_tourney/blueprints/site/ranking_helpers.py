"""
byceps.services.netsession_tourney.blueprints.site.ranking_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.models import MatchState, StageType

from .match_helpers import is_skipped_double_grand_final_result
from .ranking_duel_row_helpers import (
    apply_duel_match,
    apply_opponent_strengths,
    build_points_ranking_rows,
    build_swiss_ranking_rows,
    DuelRankingState,
)
from .ranking_row_helpers import (
    apply_ffa_match,
    apply_flatout2_match,
    assign_shared_ranks,
    ffa_ranking_sort_key,
    ffa_ranking_tie_value,
    flatout2_ranking_sort_key,
    flatout2_ranking_tie_value,
    has_played_rows,
    new_ffa_ranking_row,
    new_flatout2_ranking_row,
)


def build_ffa_ranking_rows(
    participants,
    matches,
    slots_by_match_id,
    results_by_match_id,
    stages_by_id,
):
    rows_by_participant_id = {
        participant.id: new_ffa_ranking_row(participant)
        for participant in participants
    }

    for match in matches:
        apply_ffa_match(
            rows_by_participant_id,
            match,
            slots_by_match_id,
            results_by_match_id,
            stages_by_id,
        )

    if not has_played_rows(rows_by_participant_id):
        return []

    rows = sorted(rows_by_participant_id.values(), key=ffa_ranking_sort_key)

    return assign_shared_ranks(rows, ffa_ranking_tie_value)


def build_flatout2_ranking_rows(
    participants,
    matches,
    slots_by_match_id,
    results_by_match_id,
    get_ffa_placement_by_slot_no,
):
    rows_by_participant_id = {
        participant.id: new_flatout2_ranking_row(participant)
        for participant in participants
    }

    for match in matches:
        apply_flatout2_match(
            rows_by_participant_id,
            match,
            slots_by_match_id,
            results_by_match_id,
            get_ffa_placement_by_slot_no,
        )

    if not has_played_rows(rows_by_participant_id):
        return []

    rows = sorted(
        rows_by_participant_id.values(), key=flatout2_ranking_sort_key
    )

    return assign_shared_ranks(rows, flatout2_ranking_tie_value)


def build_ranking_rows(
    participants,
    matches,
    slots_by_match_id,
    results_by_match_id,
    *,
    stage_type: StageType | None = None,
):
    duel_state = DuelRankingState(participants)

    for match in matches:
        apply_duel_match(
            duel_state,
            match,
            slots_by_match_id,
            results_by_match_id,
            stage_type,
        )

    apply_opponent_strengths(duel_state)

    if not has_played_rows(duel_state.stats_by_participant_id):
        return []

    rows = list(duel_state.stats_by_participant_id.values())
    if stage_type == StageType.swiss:
        return build_swiss_ranking_rows(
            rows, duel_state.head_to_head_winner_id_by_pair
        )

    return build_points_ranking_rows(rows, duel_state)


def has_rankable_results(
    matches,
    slots_by_match_id,
    results_by_match_id,
):
    for match in matches:
        if not any(
            slot.participant_id is not None
            for slot in slots_by_match_id.get(match.id, [])
        ):
            continue

        result = results_by_match_id.get(match.id)
        if result is None or is_skipped_double_grand_final_result(result):
            continue

        return True

    return False


def are_all_rankable_matches_completed(
    matches,
    slots_by_match_id,
):
    relevant_matches = [
        match
        for match in matches
        if any(
            slot.participant_id is not None
            for slot in slots_by_match_id.get(match.id, [])
        )
    ]

    if not relevant_matches:
        return False

    return all(
        match.state == MatchState.completed for match in relevant_matches
    )

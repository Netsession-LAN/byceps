"""
byceps.services.netsession_tourney.ranking_order
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Order of ranked participants: sort keys and tie-breakers (including the
Swiss head-to-head comparison).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .models import (
    ParticipantID,
    StageType,
)


def sort_ranked_participant_ids(
    rows_by_participant_id: dict[ParticipantID, dict[str, Any]],
    *,
    stage_type: str | None = None,
    head_to_head_winner_id_by_pair: dict[
        frozenset[ParticipantID], ParticipantID
    ]
    | None = None,
    is_ffa_scoring_stage: bool,
) -> list[ParticipantID]:
    if not is_ffa_scoring_stage and stage_type == StageType.swiss.value:
        return _sort_swiss_ranked_participant_ids(
            rows_by_participant_id, head_to_head_winner_id_by_pair
        )

    if (
        not is_ffa_scoring_stage
        and stage_type == StageType.round_robin_groups.value
    ):
        return _sort_round_robin_ranked_participant_ids(
            rows_by_participant_id, head_to_head_winner_id_by_pair
        )

    return _sort_default_ranked_participant_ids(
        rows_by_participant_id, is_ffa_scoring_stage=is_ffa_scoring_stage
    )


def _sort_swiss_ranked_participant_ids(
    rows_by_participant_id: dict[ParticipantID, dict[str, Any]],
    head_to_head_winner_id_by_pair: dict[
        frozenset[ParticipantID], ParticipantID
    ]
    | None,
) -> list[ParticipantID]:
    swiss_head_to_head_scores = _build_swiss_head_to_head_scores(
        rows_by_participant_id, head_to_head_winner_id_by_pair
    )
    return [
        participant_id
        for participant_id, _ in sorted(
            rows_by_participant_id.items(),
            key=lambda item: (
                -item[1].get('wins', 0),
                item[1].get('losses', 0),
                -item[1].get('buchholz', 0),
                -item[1].get('opponent_wl_sum', 0),
                -item[1].get('second_order_sos', 0),
                -swiss_head_to_head_scores.get(item[0], 0),
                -item[1].get('round_diff', 0),
                -item[1].get('round_wins', 0),
                (item[1]['seed'] if item[1]['seed'] is not None else 999_999),
                item[1]['created_at'],
            ),
        )
    ]


def _sort_round_robin_ranked_participant_ids(
    rows_by_participant_id: dict[ParticipantID, dict[str, Any]],
    head_to_head_winner_id_by_pair: dict[
        frozenset[ParticipantID], ParticipantID
    ]
    | None,
) -> list[ParticipantID]:
    tie_break_values_by_participant_id: dict[
        ParticipantID, tuple[int, int, int, int]
    ] = {}
    participants_by_points: dict[int, list[ParticipantID]] = defaultdict(list)
    for participant_id, row in rows_by_participant_id.items():
        participants_by_points[row.get('match_points', 0)].append(
            participant_id
        )

    for participant_ids in participants_by_points.values():
        direct_compare_scores = {
            participant_id: 0 for participant_id in participant_ids
        }
        if (
            len(participant_ids) == 2
            and head_to_head_winner_id_by_pair is not None
        ):
            winner_id = head_to_head_winner_id_by_pair.get(
                frozenset(participant_ids)
            )
            if winner_id in direct_compare_scores:
                direct_compare_scores[winner_id] = 1

        for participant_id in participant_ids:
            row = rows_by_participant_id[participant_id]
            tie_break_values_by_participant_id[participant_id] = (
                row.get('match_points', 0),
                direct_compare_scores[participant_id],
                row.get('round_diff', 0),
                row.get('round_wins', 0),
            )

    return [
        participant_id
        for participant_id, _ in sorted(
            rows_by_participant_id.items(),
            key=lambda item: (
                -tie_break_values_by_participant_id[item[0]][0],
                -tie_break_values_by_participant_id[item[0]][1],
                -tie_break_values_by_participant_id[item[0]][2],
                -tie_break_values_by_participant_id[item[0]][3],
                (item[1]['seed'] if item[1]['seed'] is not None else 999_999),
                item[1]['created_at'],
            ),
        )
    ]


def _sort_default_ranked_participant_ids(
    rows_by_participant_id: dict[ParticipantID, dict[str, Any]],
    *,
    is_ffa_scoring_stage: bool,
) -> list[ParticipantID]:
    return [
        participant_id
        for participant_id, _ in sorted(
            rows_by_participant_id.items(),
            key=lambda item: (
                (-item[1]['total_points'] if is_ffa_scoring_stage else 0),
                (-item[1]['points'] if is_ffa_scoring_stage else 0),
                (-item[1]['kills'] if is_ffa_scoring_stage else 0),
                (
                    (
                        item[1]['placement']
                        if item[1]['placement'] is not None
                        else 999_999
                    )
                    if is_ffa_scoring_stage
                    else 0
                ),
                -item[1]['wins'],
                item[1]['losses'],
                item[1]['seed'] if item[1]['seed'] is not None else 999_999,
                item[1]['created_at'],
            ),
        )
    ]


def _build_swiss_head_to_head_scores(
    rows_by_participant_id: dict[ParticipantID, dict[str, Any]],
    head_to_head_winner_id_by_pair: dict[
        frozenset[ParticipantID], ParticipantID
    ]
    | None,
) -> dict[ParticipantID, int]:
    scores_by_participant_id = {
        participant_id: 0 for participant_id in rows_by_participant_id
    }
    if head_to_head_winner_id_by_pair is None:
        return scores_by_participant_id

    participant_ids_by_base_tie_values: dict[
        tuple[int, int, int, int, int], list[ParticipantID]
    ] = defaultdict(list)
    for participant_id, row in rows_by_participant_id.items():
        participant_ids_by_base_tie_values[
            (
                row.get('wins', 0),
                row.get('losses', 0),
                row.get('buchholz', 0),
                row.get('opponent_wl_sum', 0),
                row.get('second_order_sos', 0),
            )
        ].append(participant_id)

    for participant_ids in participant_ids_by_base_tie_values.values():
        if len(participant_ids) != 2:
            continue

        winner_id = head_to_head_winner_id_by_pair.get(
            frozenset(participant_ids)
        )
        if winner_id in scores_by_participant_id:
            scores_by_participant_id[winner_id] = 1

    return scores_by_participant_id

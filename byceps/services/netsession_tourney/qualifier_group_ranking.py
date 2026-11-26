"""
byceps.services.netsession_tourney.qualifier_group_ranking
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ranking the participants of each group of a source stage.
"""

from __future__ import annotations

from collections import defaultdict

from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyMatch,
)
from .models import (
    ParticipantID,
    StageID,
    StageType,
    TournamentID,
)
from .ranking_order import (
    sort_ranked_participant_ids,
)
from .stage_ranking import (
    build_stage_ranking_data,
    StageRankingData,
)


def get_ranked_participant_ids_by_group_for_stage(
    stage_id: StageID,
    tournament_id: TournamentID,
) -> Result[list[list[ParticipantID]], str]:
    ranking_data_result = build_stage_ranking_data(stage_id, tournament_id)
    if ranking_data_result.is_err():
        return Err(ranking_data_result.unwrap_err())

    ranking_data = ranking_data_result.unwrap()
    if ranking_data.db_stage.type != StageType.round_robin_groups.value:
        return Err(
            'Qualifikation pro Gruppe gibt es nur bei Round-Robin-Gruppen.'
        )

    (
        connected_participant_ids_by_participant_id,
        first_match_no_by_participant_id,
    ) = _build_group_participant_connections(ranking_data)

    visited_participant_ids: set[ParticipantID] = set()
    ranked_group_participant_ids: list[tuple[int, list[ParticipantID]]] = []

    for participant_id in ranking_data.rows_by_participant_id:
        if participant_id in visited_participant_ids:
            continue

        group_participant_ids = _collect_connected_participant_ids(
            participant_id,
            connected_participant_ids_by_participant_id,
            visited_participant_ids,
        )
        ranked_group_participant_ids.append(
            _rank_group(
                ranking_data,
                group_participant_ids,
                first_match_no_by_participant_id,
            )
        )

    ranked_group_participant_ids.sort(key=lambda item: item[0])

    return Ok(
        [
            sorted_group_participant_ids
            for _, sorted_group_participant_ids in ranked_group_participant_ids
        ]
    )


def _rank_group(
    ranking_data: StageRankingData,
    group_participant_ids: set[ParticipantID],
    first_match_no_by_participant_id: dict[ParticipantID, int],
) -> tuple[int, list[ParticipantID]]:
    """Return the group's first match number and its ranked participants."""
    group_rows_by_participant_id = {
        group_participant_id: ranking_data.rows_by_participant_id[
            group_participant_id
        ]
        for group_participant_id in group_participant_ids
    }
    sorted_group_participant_ids = sort_ranked_participant_ids(
        group_rows_by_participant_id,
        stage_type=ranking_data.db_stage.type,
        head_to_head_winner_id_by_pair=(
            ranking_data.head_to_head_winner_id_by_pair
        ),
        is_ffa_scoring_stage=ranking_data.is_ffa_scoring_stage,
    )
    first_match_no = min(
        first_match_no_by_participant_id.get(group_participant_id, 999_999)
        for group_participant_id in group_participant_ids
    )
    return first_match_no, sorted_group_participant_ids


def _build_group_participant_connections(
    ranking_data: StageRankingData,
) -> tuple[dict[ParticipantID, set[ParticipantID]], dict[ParticipantID, int]]:
    """Return which participants played each other, and each participant's
    first match number.
    """
    connected_participant_ids_by_participant_id: dict[
        ParticipantID, set[ParticipantID]
    ] = defaultdict(set)
    first_match_no_by_participant_id: dict[ParticipantID, int] = {}

    for db_match in ranking_data.db_matches:
        match_participant_ids = _get_match_participant_ids(
            ranking_data, db_match
        )
        if not match_participant_ids:
            continue

        _record_first_match_no(
            first_match_no_by_participant_id,
            match_participant_ids,
            db_match.match_no,
        )
        _connect_participants(
            connected_participant_ids_by_participant_id, match_participant_ids
        )

    return (
        connected_participant_ids_by_participant_id,
        first_match_no_by_participant_id,
    )


def _get_match_participant_ids(
    ranking_data: StageRankingData, db_match: DbNetsessionTourneyMatch
) -> list[ParticipantID]:
    return [
        participant_id
        for participant_id in {
            db_slot.participant_id
            for db_slot in ranking_data.slots_by_match_id.get(db_match.id, [])
            if db_slot.participant_id is not None
        }
    ]


def _record_first_match_no(
    first_match_no_by_participant_id: dict[ParticipantID, int],
    participant_ids: list[ParticipantID],
    match_no: int,
) -> None:
    for participant_id in participant_ids:
        current_first_match_no = first_match_no_by_participant_id.get(
            participant_id
        )
        if current_first_match_no is None or match_no < current_first_match_no:
            first_match_no_by_participant_id[participant_id] = match_no


def _connect_participants(
    connected_participant_ids_by_participant_id: dict[
        ParticipantID, set[ParticipantID]
    ],
    participant_ids: list[ParticipantID],
) -> None:
    """Connect each of the participants with each other one."""
    for index, participant_id in enumerate(participant_ids):
        for other_participant_id in participant_ids[index + 1 :]:
            connected_participant_ids_by_participant_id[participant_id].add(
                other_participant_id
            )
            connected_participant_ids_by_participant_id[
                other_participant_id
            ].add(participant_id)


def _collect_connected_participant_ids(
    start_participant_id: ParticipantID,
    connected_participant_ids_by_participant_id: dict[
        ParticipantID, set[ParticipantID]
    ],
    visited_participant_ids: set[ParticipantID],
) -> set[ParticipantID]:
    """Collect the group of `start_participant_id` (and mark it visited)."""
    stack = [start_participant_id]
    group_participant_ids: set[ParticipantID] = set()
    while stack:
        current_participant_id = stack.pop()
        if current_participant_id in visited_participant_ids:
            continue

        visited_participant_ids.add(current_participant_id)
        group_participant_ids.add(current_participant_id)
        stack.extend(
            connected_participant_ids_by_participant_id.get(
                current_participant_id, set()
            )
        )

    return group_participant_ids

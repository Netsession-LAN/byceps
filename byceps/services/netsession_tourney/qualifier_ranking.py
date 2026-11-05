"""
byceps.services.netsession_tourney.qualifier_ranking
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Qualifiers from a source stage: ranked participants per group or per match, and how many qualify.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

from byceps.database import db
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyStage,
)
from .ffa_qualifiers import (
    _get_ffa_single_elimination_qualifier_ids,
)
from .models import (
    MatchID,
    MatchState,
    ParticipantID,
    Stage,
    StageID,
    StageType,
    TournamentID,
)
from .ranking_order import (
    _sort_ranked_participant_ids,
)
from .stage_builder_settings import (
    _get_stage_builder_main_stage_size,
)
from .stage_ranking import (
    _build_stage_ranking_data,
    _StageRankingData,
)


def _get_ranked_participant_ids_by_match_for_stage(
    stage_id: StageID,
    tournament_id: TournamentID,
    *,
    top_n_per_match: int,
) -> Result[list[ParticipantID], str]:
    if top_n_per_match < 1:
        return Err('ungültige Top-Anzahl pro Match.')

    db_stage = db.session.get(DbNetsessionTourneyStage, stage_id)
    if db_stage is None:
        return Err('existiert nicht.')

    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(stage_id=stage_id, tournament_id=tournament_id)
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()
    if not db_matches:
        return Err('contains no generated matches yet.')

    if any(db_match.state != MatchState.completed.value for db_match in db_matches):
        return Err('is not fully completed yet.')

    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot).filter(
            DbNetsessionTourneyMatchSlot.match_id.in_(
                [db_match.id for db_match in db_matches]
            )
        )
    ).all()
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = defaultdict(
        list
    )
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)

    ranked_participant_ids: list[ParticipantID] = []
    for db_match in db_matches:
        ranked_participant_ids.extend(
            _get_ffa_single_elimination_qualifier_ids(
                db_match.id,
                sorted(
                    slots_by_match_id.get(db_match.id, []),
                    key=lambda db_slot: db_slot.slot_no,
                ),
                top_n_per_match,
            )
        )

    if not ranked_participant_ids:
        return Err('contains no rankable participants.')

    return Ok(ranked_participant_ids)


def _get_effective_qualifier_top_n_for_source_stage(
    stage: Stage,
    db_source_stage: DbNetsessionTourneyStage,
    tournament_id: TournamentID,
    *,
    selection_mode: str,
) -> Result[int, str]:
    if not (stage.settings or {}).get('builder_auto_qualifier_count'):
        raw_top_n = (stage.settings or {}).get('qualifier_top_n', 1)
        try:
            top_n = int(raw_top_n)
        except (TypeError, ValueError):
            return Err('Ungültige Top-Anzahl für die Qualifikation.')
        if top_n < 1 or top_n > 128:
            return Err('Die Top-Anzahl für die Qualifikation muss zwischen 1 und 128 liegen.')
        return Ok(top_n)

    main_stage_size = _get_stage_builder_main_stage_size(stage)
    if main_stage_size is None:
        return Err('Ungültige Größe der Main Stage im Baukasten.')

    if selection_mode == 'per_stage':
        return Ok(main_stage_size)

    if db_source_stage.type != StageType.round_robin_groups.value:
        return Err(
            'Automatische Qualifikanten pro Gruppe gibt es nur mit einer Round-Robin-Gruppen-Stage als Quelle.'
        )

    ranked_group_participant_ids_result = _get_ranked_participant_ids_by_group_for_stage(
        db_source_stage.id,
        tournament_id,
    )
    if ranked_group_participant_ids_result.is_err():
        return Err(ranked_group_participant_ids_result.unwrap_err())

    ranked_groups = ranked_group_participant_ids_result.unwrap()
    group_count = len(ranked_groups)
    if group_count < 1:
        return Err('enthält keine gewerteten Gruppen.')
    if main_stage_size % group_count != 0:
        return Err(
            'die Qualifikanten aus den Gruppen lassen sich nicht gleichmäßig auf die Größe der Main Stage verteilen.'
        )

    top_n = main_stage_size // group_count
    if top_n < 1:
        return Err('Ungültige Top-Anzahl für die Qualifikation.')

    return Ok(top_n)


def _get_ranked_participant_ids_by_group_for_stage(
    stage_id: StageID,
    tournament_id: TournamentID,
) -> Result[list[list[ParticipantID]], str]:
    ranking_data_result = _build_stage_ranking_data(stage_id, tournament_id)
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

        group_rows_by_participant_id = {
            group_participant_id: ranking_data.rows_by_participant_id[
                group_participant_id
            ]
            for group_participant_id in group_participant_ids
        }
        sorted_group_participant_ids = _sort_ranked_participant_ids(
            group_rows_by_participant_id,
            stage_type=ranking_data.db_stage.type,
            head_to_head_winner_id_by_pair=(
                ranking_data.head_to_head_winner_id_by_pair
            ),
            is_ffa_scoring_stage=ranking_data.is_ffa_scoring_stage,
        )
        first_match_no = min(
            first_match_no_by_participant_id.get(
                group_participant_id, 999_999
            )
            for group_participant_id in group_participant_ids
        )
        ranked_group_participant_ids.append(
            (first_match_no, sorted_group_participant_ids)
        )

    ranked_group_participant_ids.sort(key=lambda item: item[0])

    return Ok(
        [
            sorted_group_participant_ids
            for _, sorted_group_participant_ids in ranked_group_participant_ids
        ]
    )


def _build_group_participant_connections(
    ranking_data: _StageRankingData,
) -> tuple[dict[ParticipantID, set[ParticipantID]], dict[ParticipantID, int]]:
    """Return which participants played each other, and each participant's
    first match number.
    """
    connected_participant_ids_by_participant_id: dict[
        ParticipantID, set[ParticipantID]
    ] = defaultdict(set)
    first_match_no_by_participant_id: dict[ParticipantID, int] = {}

    for db_match in ranking_data.db_matches:
        match_participant_ids = [
            participant_id
            for participant_id in {
                db_slot.participant_id
                for db_slot in ranking_data.slots_by_match_id.get(db_match.id, [])
                if db_slot.participant_id is not None
            }
        ]
        if not match_participant_ids:
            continue

        for participant_id in match_participant_ids:
            current_first_match_no = first_match_no_by_participant_id.get(
                participant_id
            )
            if (
                current_first_match_no is None
                or db_match.match_no < current_first_match_no
            ):
                first_match_no_by_participant_id[participant_id] = (
                    db_match.match_no
                )

        for index, participant_id in enumerate(match_participant_ids):
            for other_participant_id in match_participant_ids[index + 1 :]:
                connected_participant_ids_by_participant_id[
                    participant_id
                ].add(other_participant_id)
                connected_participant_ids_by_participant_id[
                    other_participant_id
                ].add(participant_id)

    return (
        connected_participant_ids_by_participant_id,
        first_match_no_by_participant_id,
    )


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

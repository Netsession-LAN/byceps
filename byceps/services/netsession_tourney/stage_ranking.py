"""
byceps.services.netsession_tourney.stage_ranking
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ranking data of a stage: points, round difference and the ranked
participant order.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from byceps.database import db
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyStage,
)
from .models import (
    MatchID,
    MatchState,
    ParticipantID,
    StageID,
    StageType,
    TournamentID,
)
from .ranking_order import (
    sort_ranked_participant_ids,
)
from .stage_ranking_rows import RankingTally, new_ranking_row
from .score_parsing import (
    get_ffa_points_per_kill,
)


@dataclass(frozen=True, kw_only=True)
class StageRankingData:
    db_stage: DbNetsessionTourneyStage
    db_matches: list[DbNetsessionTourneyMatch]
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]]
    rows_by_participant_id: dict[ParticipantID, dict[str, Any]]
    head_to_head_winner_id_by_pair: dict[frozenset[ParticipantID], ParticipantID]
    opponent_ids_by_participant_id: dict[ParticipantID, list[ParticipantID]]
    is_ffa_scoring_stage: bool


def get_ranked_participant_ids_for_stage(
    stage_id: StageID,
    tournament_id: TournamentID,
) -> Result[list[ParticipantID], str]:
    ranking_data_result = build_stage_ranking_data(stage_id, tournament_id)
    if ranking_data_result.is_err():
        return Err(ranking_data_result.unwrap_err())

    ranking_data = ranking_data_result.unwrap()
    ranked_participant_ids = sort_ranked_participant_ids(
        ranking_data.rows_by_participant_id,
        stage_type=ranking_data.db_stage.type,
        head_to_head_winner_id_by_pair=(
            ranking_data.head_to_head_winner_id_by_pair
        ),
        is_ffa_scoring_stage=ranking_data.is_ffa_scoring_stage,
    )

    if not ranked_participant_ids:
        return Err('contains no rankable participants.')

    return Ok(ranked_participant_ids)


FFA_SCORING_STAGE_TYPES = {
    StageType.ffa_simple.value,
    StageType.ffa_single_elimination.value,
    StageType.ffa_flatout2_single_elimination.value,
}


def build_stage_ranking_data(
    stage_id: StageID,
    tournament_id: TournamentID,
) -> Result[StageRankingData, str]:
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
        return Err('no matches generated yet.')

    if any(match.state != MatchState.completed.value for match in db_matches):
        return Err('is not fully completed yet.')

    match_ids = [match.id for match in db_matches]
    slots_by_match_id, participant_ids = _load_slots(match_ids)
    if not participant_ids:
        return Err('contains no participants.')

    tally = RankingTally(
        rows_by_participant_id=_new_rows(tournament_id, participant_ids),
        is_ffa_scoring_stage=db_stage.type in FFA_SCORING_STAGE_TYPES,
        is_swiss_stage=db_stage.type == StageType.swiss.value,
        points_per_kill=get_ffa_points_per_kill(dict(db_stage.settings_json or {})),
    )
    db_results = db.session.scalars(
        select(DbNetsessionTourneyMatchResult).filter(
            DbNetsessionTourneyMatchResult.match_id.in_(match_ids)
        )
    ).all()
    for db_result in db_results:
        tally.add_result(db_result, slots_by_match_id.get(db_result.match_id, []))
    tally.add_strength_of_schedule()

    return Ok(
        StageRankingData(
            db_stage=db_stage,
            db_matches=db_matches,
            slots_by_match_id=slots_by_match_id,
            rows_by_participant_id=tally.rows_by_participant_id,
            head_to_head_winner_id_by_pair=tally.head_to_head_winner_id_by_pair,
            opponent_ids_by_participant_id=tally.opponent_ids_by_participant_id,
            is_ffa_scoring_stage=tally.is_ffa_scoring_stage,
        )
    )


def _load_slots(match_ids):
    """Return the slots per match and all participants in them."""
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot).filter(
            DbNetsessionTourneyMatchSlot.match_id.in_(match_ids)
        )
    ).all()
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = (
        defaultdict(list)
    )
    participant_ids: set[ParticipantID] = set()
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)
        if db_slot.participant_id is not None:
            participant_ids.add(db_slot.participant_id)
    return slots_by_match_id, participant_ids


def _new_rows(tournament_id, participant_ids) -> dict[ParticipantID, dict[str, Any]]:
    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter_by(tournament_id=tournament_id)
        .filter(DbNetsessionTourneyParticipant.id.in_(participant_ids))
    ).all()
    db_participant_by_id = {p.id: p for p in db_participants}
    return {
        participant_id: new_ranking_row(db_participant_by_id[participant_id])
        for participant_id in participant_ids
        if participant_id in db_participant_by_id
    }

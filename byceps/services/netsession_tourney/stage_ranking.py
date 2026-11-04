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
    _sort_ranked_participant_ids,
)
from .tournament_queries import (
    _get_ffa_points_per_kill,
    _is_walkover_score_json,
    _parse_match_result_slot_scores,
    _parse_numeric_score_value,
)


@dataclass(frozen=True, kw_only=True)
class _StageRankingData:
    db_stage: DbNetsessionTourneyStage
    db_matches: list[DbNetsessionTourneyMatch]
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]]
    rows_by_participant_id: dict[ParticipantID, dict[str, Any]]
    head_to_head_winner_id_by_pair: dict[frozenset[ParticipantID], ParticipantID]
    opponent_ids_by_participant_id: dict[ParticipantID, list[ParticipantID]]
    is_ffa_scoring_stage: bool


def _get_ranked_participant_ids_for_stage(
    stage_id: StageID,
    tournament_id: TournamentID,
) -> Result[list[ParticipantID], str]:
    ranking_data_result = _build_stage_ranking_data(stage_id, tournament_id)
    if ranking_data_result.is_err():
        return Err(ranking_data_result.unwrap_err())

    ranking_data = ranking_data_result.unwrap()
    ranked_participant_ids = _sort_ranked_participant_ids(
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


def _build_stage_ranking_data(
    stage_id: StageID,
    tournament_id: TournamentID,
) -> Result[_StageRankingData, str]:
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

    if not participant_ids:
        return Err('contains no participants.')

    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter_by(tournament_id=tournament_id)
        .filter(DbNetsessionTourneyParticipant.id.in_(participant_ids))
    ).all()
    db_participant_by_id = {
        participant.id: participant for participant in db_participants
    }

    rows_by_participant_id: dict[ParticipantID, dict[str, Any]] = {}
    for participant_id in participant_ids:
        db_participant = db_participant_by_id.get(participant_id)
        if db_participant is None:
            continue

        rows_by_participant_id[participant_id] = {
            'total_points': 0,
            'points': 0,
            'wins': 0,
            'losses': 0,
            'match_points': 0,
            'round_wins': 0,
            'round_losses': 0,
            'round_diff': 0,
            'buchholz': 0,
            'opponent_wl_sum': 0,
            'second_order_sos': 0,
            'kills': 0,
            'placement': None,
            'seed': db_participant.seed,
            'created_at': db_participant.created_at,
        }

    is_ffa_scoring_stage = db_stage.type in {
        StageType.ffa_simple.value,
        StageType.ffa_single_elimination.value,
        StageType.ffa_flatout2_single_elimination.value,
    }
    is_swiss_stage = db_stage.type == StageType.swiss.value
    points_per_kill = _get_ffa_points_per_kill(dict(db_stage.settings_json or {}))

    db_results = db.session.scalars(
        select(DbNetsessionTourneyMatchResult).filter(
            DbNetsessionTourneyMatchResult.match_id.in_(match_ids)
        )
    ).all()
    opponent_ids_by_participant_id: dict[ParticipantID, list[ParticipantID]] = (
        defaultdict(list)
    )
    head_to_head_winner_id_by_pair: dict[
        frozenset[ParticipantID], ParticipantID
    ] = {}
    for db_result in db_results:
        db_match_slots = slots_by_match_id.get(db_result.match_id, [])
        real_match_slots = [
            db_slot
            for db_slot in db_match_slots
            if db_slot.participant_id is not None
        ]
        real_participant_ids = [
            db_slot.participant_id
            for db_slot in real_match_slots
            if db_slot.participant_id is not None
        ]
        winner_participant_id = None
        if db_result.winner_slot is not None:
            winner_participant_id = next(
                (
                    slot.participant_id
                    for slot in db_match_slots
                    if slot.slot_no == db_result.winner_slot
                ),
                None,
            )

        placement_by_slot_no: dict[int, int] = {}
        points_by_slot_no: dict[int, int] = {}
        if is_ffa_scoring_stage:
            raw_ranking = db_result.ranking_json or {}
            raw_placements = raw_ranking.get('placements')
            if isinstance(raw_placements, dict):
                for db_slot in db_match_slots:
                    raw_value = raw_placements.get(str(db_slot.slot_no))
                    if raw_value is None:
                        raw_value = raw_placements.get(db_slot.slot_no)
                    try:
                        placement_by_slot_no[db_slot.slot_no] = int(raw_value)
                    except (TypeError, ValueError):
                        continue
            raw_points = raw_ranking.get('points')
            if isinstance(raw_points, dict):
                for db_slot in db_match_slots:
                    raw_value = raw_points.get(str(db_slot.slot_no))
                    if raw_value is None:
                        raw_value = raw_points.get(db_slot.slot_no)
                    try:
                        points_by_slot_no[db_slot.slot_no] = int(raw_value)
                    except (TypeError, ValueError):
                        continue

        score_slots = _parse_match_result_slot_scores(
            real_match_slots,
            db_result.score_json,
            winner_slot=db_result.winner_slot,
        )
        is_walkover_result = _is_walkover_score_json(db_result.score_json)

        if (
            len(real_participant_ids) == 2
            and winner_participant_id in real_participant_ids
            and not (is_swiss_stage and is_walkover_result)
        ):
            participant_a, participant_b = real_participant_ids
            opponent_ids_by_participant_id[participant_a].append(
                participant_b
            )
            opponent_ids_by_participant_id[participant_b].append(
                participant_a
            )
            head_to_head_winner_id_by_pair[
                frozenset(real_participant_ids)
            ] = winner_participant_id

        for db_slot in db_match_slots:
            participant_id = db_slot.participant_id
            if participant_id is None:
                continue

            row = rows_by_participant_id.get(participant_id)
            if row is None:
                continue

            if is_ffa_scoring_stage:
                row['points'] += points_by_slot_no.get(db_slot.slot_no, 0)
                raw_kills = score_slots.get(str(db_slot.slot_no))
                if raw_kills is None:
                    raw_kills = score_slots.get(db_slot.slot_no)
                try:
                    row['kills'] += int(raw_kills)
                except (TypeError, ValueError):
                    pass
                row['total_points'] = row['points'] + (
                    row['kills'] * points_per_kill
                )

                placement = placement_by_slot_no.get(db_slot.slot_no)
                if (
                    placement is not None
                    and (
                        row['placement'] is None
                        or placement < row['placement']
                    )
                ):
                    row['placement'] = placement

            if (
                winner_participant_id is None
                or len(real_participant_ids) < 2
            ):
                continue

            if participant_id == winner_participant_id:
                row['wins'] += 1
                row['match_points'] += 3
            else:
                row['losses'] += 1

            if len(real_participant_ids) != 2:
                continue

            if is_swiss_stage and is_walkover_result:
                continue

            raw_round_wins = score_slots.get(str(db_slot.slot_no))
            if raw_round_wins is None:
                raw_round_wins = score_slots.get(db_slot.slot_no)
            round_wins = _parse_numeric_score_value(raw_round_wins)

            round_losses = sum(
                _parse_numeric_score_value(
                    score_slots.get(str(other_slot.slot_no))
                    if score_slots.get(str(other_slot.slot_no)) is not None
                    else score_slots.get(other_slot.slot_no)
                )
                for other_slot in real_match_slots
                if other_slot.slot_no != db_slot.slot_no
            )
            row['round_wins'] += round_wins
            row['round_losses'] += round_losses
            row['round_diff'] = row['round_wins'] - row['round_losses']

    for participant_id, row in rows_by_participant_id.items():
        row['buchholz'] = sum(
            rows_by_participant_id.get(opponent_id, {}).get('wins', 0)
            for opponent_id in opponent_ids_by_participant_id.get(
                participant_id, []
            )
        )
        row['opponent_wl_sum'] = sum(
            rows_by_participant_id.get(opponent_id, {}).get('wins', 0)
            - rows_by_participant_id.get(opponent_id, {}).get('losses', 0)
            for opponent_id in opponent_ids_by_participant_id.get(
                participant_id, []
            )
        )
    for participant_id, row in rows_by_participant_id.items():
        row['second_order_sos'] = sum(
            rows_by_participant_id.get(opponent_id, {}).get(
                'opponent_wl_sum', 0
            )
            for opponent_id in opponent_ids_by_participant_id.get(
                participant_id, []
            )
        )

    return Ok(
        _StageRankingData(
            db_stage=db_stage,
            db_matches=db_matches,
            slots_by_match_id=slots_by_match_id,
            rows_by_participant_id=rows_by_participant_id,
            head_to_head_winner_id_by_pair=head_to_head_winner_id_by_pair,
            opponent_ids_by_participant_id=opponent_ids_by_participant_id,
            is_ffa_scoring_stage=is_ffa_scoring_stage,
        )
    )

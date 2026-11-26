"""
byceps.services.netsession_tourney.discord_result_summaries_match
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Discord result summary of a single match (duel or FFA).
"""

from __future__ import annotations

from typing import Any

from .dbmodels import (
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
)
from .models import (
    ParticipantID,
    Stage,
    StageType,
)
from .score_parsing import (
    parse_match_result_slot_scores,
)


def build_discord_match_result_summary(
    *,
    stage: Stage,
    db_slots: list[DbNetsessionTourneyMatchSlot],
    db_participants_by_id: dict[ParticipantID, DbNetsessionTourneyParticipant],
    winner_slot: int | None,
    score_data: dict[str, Any],
    ranking_data: dict[str, Any],
) -> dict[str, Any] | None:
    occupied_slots = [
        db_slot
        for db_slot in sorted(db_slots, key=lambda item: item.slot_no)
        if db_slot.participant_id is not None
        and db_slot.participant_id in db_participants_by_id
    ]
    if not occupied_slots:
        return None

    is_ffa_stage = stage.type in {
        StageType.ffa_simple,
        StageType.ffa_single_elimination,
        StageType.ffa_flatout2_single_elimination,
    }

    if is_ffa_stage:
        return _build_discord_ffa_match_result_summary(
            occupied_slots, db_participants_by_id, ranking_data
        )

    return _build_discord_duel_match_result_summary(
        occupied_slots, db_slots, db_participants_by_id, winner_slot, score_data
    )


def _build_discord_ffa_match_result_summary(
    occupied_slots: list[DbNetsessionTourneyMatchSlot],
    db_participants_by_id: dict[ParticipantID, DbNetsessionTourneyParticipant],
    ranking_data: dict[str, Any],
) -> dict[str, Any] | None:
    raw_placements = _get_discord_ranking_data_entry(ranking_data, 'placements')
    raw_points = _get_discord_ranking_data_entry(ranking_data, 'points')
    if not isinstance(raw_placements, dict):
        return None

    rows: list[dict[str, Any]] = []
    for db_slot in occupied_slots:
        row = _build_discord_ffa_result_row(
            db_slot, db_participants_by_id, raw_placements, raw_points
        )
        if row is not None:
            rows.append(row)

    if not rows:
        return None

    rows.sort(key=lambda item: (item['position'], item['participant_name']))
    return {'format': 'ffa', 'rows': rows}


def _get_discord_ranking_data_entry(ranking_data: Any, key: str) -> Any:
    return ranking_data.get(key) if isinstance(ranking_data, dict) else None


def _build_discord_ffa_result_row(
    db_slot: DbNetsessionTourneyMatchSlot,
    db_participants_by_id: dict[ParticipantID, DbNetsessionTourneyParticipant],
    raw_placements: dict[Any, Any],
    raw_points: Any,
) -> dict[str, Any] | None:
    participant = db_participants_by_id.get(db_slot.participant_id)
    if participant is None:
        return None

    placement = _get_discord_slot_keyed_value(raw_placements, db_slot.slot_no)
    if placement is None:
        return None

    points = None
    if isinstance(raw_points, dict):
        points = _get_discord_slot_keyed_value(raw_points, db_slot.slot_no)

    return {
        'position': int(placement),
        'participant_name': participant.name,
        'points': points,
    }


def _get_discord_slot_keyed_value(mapping: dict[Any, Any], slot_no: int) -> Any:
    value = mapping.get(str(slot_no))
    if value is None:
        value = mapping.get(slot_no)
    return value


def _build_discord_duel_match_result_summary(
    occupied_slots: list[DbNetsessionTourneyMatchSlot],
    db_slots: list[DbNetsessionTourneyMatchSlot],
    db_participants_by_id: dict[ParticipantID, DbNetsessionTourneyParticipant],
    winner_slot: int | None,
    score_data: dict[str, Any],
) -> dict[str, Any] | None:
    parsed_scores = parse_match_result_slot_scores(
        db_slots, score_data, winner_slot=winner_slot
    )
    rows = []
    for db_slot in occupied_slots:
        participant = db_participants_by_id.get(db_slot.participant_id)
        if participant is None:
            continue

        rows.append(
            {
                'slot_no': db_slot.slot_no,
                'participant_name': participant.name,
                'score': parsed_scores.get(db_slot.slot_no),
                'is_winner': winner_slot == db_slot.slot_no,
            }
        )

    if not rows:
        return None

    rows.sort(
        key=lambda item: (
            0 if item['is_winner'] else 1,
            item['slot_no'],
        )
    )
    return {'format': 'duel', 'rows': rows}

"""
byceps.services.netsession_tourney.match_advancement_slots
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Downstream slot updates when a match advances its participants.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from byceps.database import db

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchSlot,
)
from .engines.base import StageEngine
from .ffa_qualifiers import (
    get_ffa_single_elimination_qualifier_ids,
)
from .models import (
    MatchID,
    MatchState,
    ParticipantID,
    SourceOutcome,
    Stage,
    StageType,
    TournamentID,
)
from .participant_state import (
    calculate_match_state_for_slots,
    get_tournament_status_value,
)


def _split_downstream_slots(
    downstream_db_slots: list[DbNetsessionTourneyMatchSlot],
) -> tuple[list[tuple[MatchID, int]], list[tuple[MatchID, int]]]:
    """Return (match ID, slot number) of the slots fed by the winner and of
    those fed by the loser."""
    downstream_winner_slots = [
        (db_slot.match_id, db_slot.slot_no)
        for db_slot in downstream_db_slots
        if db_slot.source_outcome != SourceOutcome.loser.value
    ]
    downstream_loser_slots = [
        (db_slot.match_id, db_slot.slot_no)
        for db_slot in downstream_db_slots
        if db_slot.source_outcome == SourceOutcome.loser.value
    ]
    return downstream_winner_slots, downstream_loser_slots


def _build_winner_slot_updates(
    stage: Stage,
    engine: StageEngine,
    *,
    source_match_id: MatchID,
    source_match_slots: list[DbNetsessionTourneyMatchSlot],
    winner_participant_id: ParticipantID | None,
    downstream_winner_slots: list[tuple[MatchID, int]],
) -> list[tuple[MatchID, int, ParticipantID | None]]:
    if stage.type in {
        StageType.ffa_single_elimination,
        StageType.ffa_flatout2_single_elimination,
    }:
        return _build_ffa_qualifier_updates(
            source_match_id, source_match_slots, downstream_winner_slots
        )

    return engine.advance(stage, winner_participant_id, downstream_winner_slots)


def _find_loser_participant_id(
    source_match_slots: list[DbNetsessionTourneyMatchSlot],
    winner_participant_id: ParticipantID | None,
) -> ParticipantID | None:
    source_participant_ids = [
        slot.participant_id
        for slot in source_match_slots
        if slot.participant_id is not None
    ]
    loser_participant_id: ParticipantID | None = None
    if winner_participant_id is not None:
        for participant_id in source_participant_ids:
            if participant_id != winner_participant_id:
                loser_participant_id = participant_id
                break
    return loser_participant_id


def _build_ffa_qualifier_updates(
    source_match_id: MatchID,
    source_match_slots: list[DbNetsessionTourneyMatchSlot],
    downstream_winner_slots: list[tuple[MatchID, int]],
) -> list[tuple[MatchID, int, ParticipantID | None]]:
    ranked_participant_ids = get_ffa_single_elimination_qualifier_ids(
        source_match_id,
        source_match_slots,
        len(downstream_winner_slots),
    )
    return [
        (
            match_id,
            slot_no,
            ranked_participant_ids[index]
            if index < len(ranked_participant_ids)
            else None,
        )
        for index, (match_id, slot_no) in enumerate(
            sorted(downstream_winner_slots, key=lambda item: (item[0], item[1]))
        )
    ]


def _apply_downstream_slot_updates(
    tournament_id: TournamentID,
    updates: list[tuple[MatchID, int, ParticipantID | None]],
) -> set[MatchID]:
    """Put participants into downstream slots and recalculate the states of
    the affected matches; return the IDs of matches that became ready."""
    ready_match_ids: set[MatchID] = set()
    for match_id, slot_no, participant_id in updates:
        db_slot = db.session.scalar(
            select(DbNetsessionTourneyMatchSlot).filter_by(
                match_id=match_id,
                slot_no=slot_no,
            )
        )
        if db_slot is None:
            continue
        db_slot.participant_id = participant_id

        db_match = db.session.get(DbNetsessionTourneyMatch, match_id)
        if db_match is None:
            continue
        previous_state = MatchState(db_match.state)
        db_match_slots = db.session.scalars(
            select(DbNetsessionTourneyMatchSlot).filter_by(match_id=match_id)
        ).all()
        next_state = calculate_match_state_for_slots(
            tournament_status=get_tournament_status_value(tournament_id),
            db_match_slots=db_match_slots,
        )
        db_match.state = next_state.value
        db_match.updated_at = datetime.utcnow()
        if (
            previous_state != MatchState.ready
            and next_state == MatchState.ready
        ):
            ready_match_ids.add(match_id)
    return ready_match_ids

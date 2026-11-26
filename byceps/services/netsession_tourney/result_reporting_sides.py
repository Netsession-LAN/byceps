"""
byceps.services.netsession_tourney.result_reporting_sides
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The sides of a reported match: loading the slots and participants,
and advancing the stage once the match is completed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from byceps.database import db
from byceps.services.user.models import UserID

from .dbmodels import (
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
)
from .double_grand_final import (
    update_optional_double_grand_final_state,
)
from .engines.registry import find_stage_engine
from .match_advancement import advance_stage_from_match, auto_advance_byes
from .models import (
    MatchID,
    Stage,
    TournamentID,
)
from .tournament_queries import ACTIVE_PARTICIPANT_STATUS_VALUES


@dataclass(frozen=True, kw_only=True)
class MatchSides:
    """The slots of a match and the active participants in them."""

    db_slots: list[DbNetsessionTourneyMatchSlot]
    db_participants_by_id: dict[Any, DbNetsessionTourneyParticipant]

    def manager_user_ids(self) -> set[UserID]:
        return {
            participant.manager_user_id
            for participant in self.db_participants_by_id.values()
            if participant.manager_user_id is not None
        }

    def slot_no_managed_by(self, user_id: UserID) -> int | None:
        for db_slot in self.db_slots:
            db_participant = (
                self.db_participants_by_id.get(db_slot.participant_id)
                if db_slot.participant_id is not None
                else None
            )
            if (
                db_participant is not None
                and db_participant.manager_user_id == user_id
            ):
                return db_slot.slot_no
        return None

    def participant_id_in_slot(self, slot_no: int | None):
        for db_slot in self.db_slots:
            if db_slot.slot_no == slot_no:
                return db_slot.participant_id
        return None


def load_match_sides(match_id: MatchID) -> MatchSides:
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=match_id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()
    participant_ids = {
        slot.participant_id for slot in db_slots if slot.participant_id
    }
    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter(DbNetsessionTourneyParticipant.id.in_(participant_ids))
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    ).all()
    return MatchSides(
        db_slots=list(db_slots),
        db_participants_by_id={p.id: p for p in db_participants},
    )


def advance_after_completion(
    tournament_id: TournamentID,
    stage: Stage,
    match_id: MatchID,
    sides: MatchSides,
    winner_slot: int | None,
) -> None:
    """Move winner (and loser) on, let byes advance, handle the reset final."""
    engine = find_stage_engine(stage.type)
    advance_stage_from_match(
        tournament_id=tournament_id,
        stage=stage,
        source_match_id=match_id,
        winner_participant_id=sides.participant_id_in_slot(winner_slot),
        engine=engine,
    )
    if engine is not None:
        auto_advance_byes(tournament_id, stage, engine=engine)
    update_optional_double_grand_final_state(
        stage=stage, source_match_id=match_id
    )

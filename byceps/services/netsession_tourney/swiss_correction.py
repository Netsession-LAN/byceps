"""
byceps.services.netsession_tourney.swiss_correction
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A changed winner in a Swiss round changes the records the later rounds
were paired by. As long as no later round was played, the later rounds are
emptied so that they are paired again with the corrected result (this
happens automatically once the corrected round is complete again). After
a later round was played, the winner can no longer change.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select

from byceps.database import db

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyResultReportReceipt,
    DbNetsessionTourneyStage,
)
from .models import MatchState, StageType


_UNPLAYED_STATES = {MatchState.pending.value, MatchState.ready.value}


def prepare_swiss_winner_change(
    db_match: DbNetsessionTourneyMatch,
) -> str | None:
    """Return why the winner cannot change, or empty the later rounds of a
    Swiss stage and return None. Not Swiss: None, nothing changed."""
    db_stage = db.session.get(DbNetsessionTourneyStage, db_match.stage_id)
    if db_stage is None or db_stage.type != StageType.swiss.value:
        return None

    later_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(stage_id=db_match.stage_id)
        .filter(DbNetsessionTourneyMatch.round_no > db_match.round_no)
    ).all()
    if not later_matches:
        return None

    later_match_ids = [match.id for match in later_matches]
    slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot).filter(
            DbNetsessionTourneyMatchSlot.match_id.in_(later_match_ids)
        )
    ).all()
    filled_count_by_match_id = _count_filled_slots_by_match_id(slots)

    played_error = _find_played_later_swiss_match(
        later_matches, filled_count_by_match_id
    )
    if played_error is not None:
        return played_error

    _empty_matches(later_matches, later_match_ids, slots)
    return None


def _count_filled_slots_by_match_id(slots) -> dict:
    filled_count_by_match_id: dict = {}
    for slot in slots:
        if slot.participant_id is not None:
            filled_count_by_match_id[slot.match_id] = (
                filled_count_by_match_id.get(slot.match_id, 0) + 1
            )
    return filled_count_by_match_id


def _find_played_later_swiss_match(
    later_matches, filled_count_by_match_id: dict
) -> str | None:
    for match in later_matches:
        is_real_match = filled_count_by_match_id.get(match.id, 0) == 2
        if is_real_match and match.state not in _UNPLAYED_STATES:
            return (
                'Der Sieger lässt sich nicht mehr ändern, weil in Runde '
                f'{match.round_no} schon gespielt wurde.'
            )
    return None


def _empty_matches(later_matches, later_match_ids, slots) -> None:
    for model in (
        DbNetsessionTourneyResultReportReceipt,
        DbNetsessionTourneyMatchResult,
    ):
        db.session.execute(
            delete(model).where(model.match_id.in_(later_match_ids))
        )
    for slot in slots:
        slot.participant_id = None
    now = datetime.utcnow()
    for match in later_matches:
        match.state = MatchState.pending.value
        match.reported_by_user_id = None
        match.confirmed_by_admin_id = None
        match.confirmation_deadline_at = None
        match.updated_at = now
        match.lock_version += 1
    db.session.flush()

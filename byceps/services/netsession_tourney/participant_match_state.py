"""
byceps.services.netsession_tourney.participant_match_state
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Match states derived from the readiness of the assigned participants.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable

from sqlalchemy import select

from byceps.database import db

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyTournament,
)
from .models import (
    MatchID,
    MatchState,
    ParticipantID,
    ParticipantStatus,
    TournamentStatus,
)
from .notification_service import (
    enqueue_match_ready_notifications,
)


BRACKET_READY_PARTICIPANT_STATUS_VALUES = {
    ParticipantStatus.ready.value,
    ParticipantStatus.checked_in.value,
    ParticipantStatus.locked.value,
}


def refresh_match_states_for_participant_readiness(
    db_tournament: DbNetsessionTourneyTournament,
    participant_id: ParticipantID,
) -> None:
    affected_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .join(
            DbNetsessionTourneyMatchSlot,
            DbNetsessionTourneyMatch.id
            == DbNetsessionTourneyMatchSlot.match_id,
        )
        .filter(DbNetsessionTourneyMatch.tournament_id == db_tournament.id)
        .filter(DbNetsessionTourneyMatchSlot.participant_id == participant_id)
        .filter(
            DbNetsessionTourneyMatch.state.in_(
                [MatchState.pending.value, MatchState.ready.value]
            )
        )
    ).all()
    if not affected_matches:
        return

    match_ids = [db_match.id for db_match in affected_matches]
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter(DbNetsessionTourneyMatchSlot.match_id.in_(match_ids))
        .order_by(
            DbNetsessionTourneyMatchSlot.match_id.asc(),
            DbNetsessionTourneyMatchSlot.slot_no.asc(),
        )
    ).all()
    slots_by_match_id = _group_slots_by_match_id(db_slots)

    participant_status_value_by_participant_id = (
        get_participant_status_value_by_participant_id_for_slots(db_slots)
    )
    now = datetime.utcnow()
    for db_match in affected_matches:
        _refresh_match_state_for_readiness(
            db_match,
            tournament_status=db_tournament.status,
            db_match_slots=slots_by_match_id.get(db_match.id, []),
            participant_status_value_by_participant_id=participant_status_value_by_participant_id,
            now=now,
        )


def _group_slots_by_match_id(
    db_slots: list[DbNetsessionTourneyMatchSlot],
) -> dict[MatchID, list[DbNetsessionTourneyMatchSlot]]:
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = (
        defaultdict(list)
    )
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)
    return slots_by_match_id


def _refresh_match_state_for_readiness(
    db_match: DbNetsessionTourneyMatch,
    *,
    tournament_status: str,
    db_match_slots: list[DbNetsessionTourneyMatchSlot],
    participant_status_value_by_participant_id: dict[ParticipantID, str],
    now: datetime,
) -> None:
    previous_state = MatchState(db_match.state)
    next_state = calculate_match_state_for_slots(
        tournament_status=tournament_status,
        db_match_slots=db_match_slots,
        participant_status_value_by_participant_id=participant_status_value_by_participant_id,
    )
    if next_state == previous_state:
        return

    db_match.state = next_state.value
    db_match.updated_at = now

    if previous_state != MatchState.ready and next_state == MatchState.ready:
        enqueue_match_ready_notifications(db_match)


def calculate_match_state_for_slots(
    *,
    tournament_status: str,
    db_match_slots: list[DbNetsessionTourneyMatchSlot],
    participant_status_value_by_participant_id: dict[ParticipantID, str]
    | None = None,
) -> MatchState:
    if not db_match_slots:
        return MatchState.pending

    participant_ids = _get_assigned_participant_ids(db_match_slots)
    if len(participant_ids) != len(db_match_slots):
        return MatchState.pending

    if participant_status_value_by_participant_id is None:
        participant_status_value_by_participant_id = (
            _get_participant_status_value_by_participant_id(participant_ids)
        )

    if any(
        participant_status_value_by_participant_id.get(participant_id)
        not in BRACKET_READY_PARTICIPANT_STATUS_VALUES
        for participant_id in participant_ids
    ):
        return MatchState.pending

    if tournament_status == TournamentStatus.live.value:
        return MatchState.ready

    return MatchState.pending


def _get_assigned_participant_ids(
    db_match_slots: list[DbNetsessionTourneyMatchSlot],
) -> list[ParticipantID]:
    return [
        db_slot.participant_id
        for db_slot in db_match_slots
        if db_slot.participant_id is not None
    ]


def get_participant_status_value_by_participant_id_for_slots(
    db_match_slots: list[DbNetsessionTourneyMatchSlot],
) -> dict[ParticipantID, str]:
    participant_ids = {
        db_slot.participant_id
        for db_slot in db_match_slots
        if db_slot.participant_id is not None
    }
    return _get_participant_status_value_by_participant_id(participant_ids)


def _get_participant_status_value_by_participant_id(
    participant_ids: Iterable[ParticipantID],
) -> dict[ParticipantID, str]:
    participant_ids = set(participant_ids)
    if not participant_ids:
        return {}

    rows = db.session.execute(
        select(
            DbNetsessionTourneyParticipant.id,
            DbNetsessionTourneyParticipant.status,
        ).filter(DbNetsessionTourneyParticipant.id.in_(participant_ids))
    ).all()
    return {participant_id: status for participant_id, status in rows}

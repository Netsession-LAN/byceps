"""
byceps.services.netsession_tourney.participant_state
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Status helpers for participants, matches and tournaments, shared by the service modules.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import UserID
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyTeamMember,
    DbNetsessionTourneyTournament,
)
from .models import (
    MatchID,
    MatchState,
    ParticipantID,
    ParticipantStatus,
    Tournament,
    TournamentID,
    TournamentStatus,
)
from .notification_service import (
    enqueue_match_ready_notifications,
)
from .tournament_queries import (
    find_db_tournament_for_party,
    ACTIVE_PARTICIPANT_STATUS_VALUES,
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
            DbNetsessionTourneyMatch.id == DbNetsessionTourneyMatchSlot.match_id,
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
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = (
        defaultdict(list)
    )
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)

    participant_status_value_by_participant_id = (
        get_participant_status_value_by_participant_id_for_slots(db_slots)
    )
    now = datetime.utcnow()
    for db_match in affected_matches:
        previous_state = MatchState(db_match.state)
        next_state = calculate_match_state_for_slots(
            tournament_status=db_tournament.status,
            db_match_slots=slots_by_match_id.get(db_match.id, []),
            participant_status_value_by_participant_id=participant_status_value_by_participant_id,
        )
        if next_state == previous_state:
            continue

        db_match.state = next_state.value
        db_match.updated_at = now

        if previous_state != MatchState.ready and next_state == MatchState.ready:
            enqueue_match_ready_notifications(db_match)


def count_active_participants_for_tournament(
    party_id: PartyID, tournament_id: TournamentID
) -> int:
    if find_db_tournament_for_party(party_id, tournament_id) is None:
        return 0

    count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyParticipant.id))
        .filter_by(tournament_id=tournament_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )
    return int(count or 0)


def get_tournament_status_value(tournament_id: TournamentID) -> str:
    return (
        db.session.scalar(
            select(DbNetsessionTourneyTournament.status).filter_by(
                id=tournament_id
            )
        )
        or TournamentStatus.draft.value
    )


def calculate_match_state_for_slots(
    *,
    tournament_status: str,
    db_match_slots: list[DbNetsessionTourneyMatchSlot],
    participant_status_value_by_participant_id: dict[ParticipantID, str] | None = None,
) -> MatchState:
    if not db_match_slots:
        return MatchState.pending

    participant_ids = [
        db_slot.participant_id
        for db_slot in db_match_slots
        if db_slot.participant_id is not None
    ]
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


def validate_participant_limit(participant_limit: int | None) -> Result[None, str]:
    if participant_limit is None:
        return Ok(None)

    if participant_limit < 2:
        return Err('Das Teilnehmerlimit muss mindestens 2 sein.')

    return Ok(None)


def is_user_already_active_participant(
    tournament_id: TournamentID, user_id: UserID
) -> bool:
    direct_assignment_exists = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyParticipant.id))
        .filter_by(tournament_id=tournament_id, user_id=user_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )
    if direct_assignment_exists:
        return True

    team_membership_exists = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyTeamMember.id))
        .join(
            DbNetsessionTourneyParticipant,
            DbNetsessionTourneyTeamMember.participant_id
            == DbNetsessionTourneyParticipant.id,
        )
        .filter(DbNetsessionTourneyTeamMember.user_id == user_id)
        .filter(DbNetsessionTourneyParticipant.tournament_id == tournament_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )
    return bool(team_membership_exists)


def is_tournament_full(
    tournament: Tournament, active_participant_count: int
) -> bool:
    return (
        tournament.participant_limit is not None
        and active_participant_count >= tournament.participant_limit
    )


def find_db_active_participant_for_user(
    tournament_id: TournamentID, user_id: UserID
) -> DbNetsessionTourneyParticipant | None:
    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant)
        .filter_by(tournament_id=tournament_id, user_id=user_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )
    if db_participant is not None:
        return db_participant

    return db.session.scalar(
        select(DbNetsessionTourneyParticipant)
        .join(
            DbNetsessionTourneyTeamMember,
            DbNetsessionTourneyTeamMember.participant_id
            == DbNetsessionTourneyParticipant.id,
        )
        .filter(DbNetsessionTourneyParticipant.tournament_id == tournament_id)
        .filter(DbNetsessionTourneyTeamMember.user_id == user_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )

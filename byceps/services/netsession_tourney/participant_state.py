"""
byceps.services.netsession_tourney.participant_state
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Status helpers for participants, matches and tournaments, shared by the service modules.
"""

from __future__ import annotations

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import UserID
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyTeamMember,
    DbNetsessionTourneyTournament,
)
from .models import (
    Tournament,
    TournamentID,
    TournamentStatus,
)
from .participant_match_state import (
    calculate_match_state_for_slots as calculate_match_state_for_slots,
    get_participant_status_value_by_participant_id_for_slots as get_participant_status_value_by_participant_id_for_slots,
    refresh_match_states_for_participant_readiness as refresh_match_states_for_participant_readiness,
)
from .tournament_queries import (
    ACTIVE_PARTICIPANT_STATUS_VALUES,
    find_db_tournament_for_party,
)


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


def validate_participant_limit(
    participant_limit: int | None,
) -> Result[None, str]:
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

"""
byceps.services.netsession_tourney.notification_recipients
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Users to notify about a match or a tournament.
"""

from __future__ import annotations

from sqlalchemy import select

from byceps.database import db
from byceps.services.user.models import UserID

from .dbmodels import (
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyTeamMember,
)
from .models import (
    MatchID,
    TournamentID,
)
from .tournament_queries import ACTIVE_PARTICIPANT_STATUS_VALUES


def get_match_involved_user_ids(match_id: MatchID) -> set[UserID]:
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot).filter_by(match_id=match_id)
    ).all()
    participant_ids = [slot.participant_id for slot in db_slots if slot.participant_id]
    if not participant_ids:
        return set()

    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter(DbNetsessionTourneyParticipant.id.in_(participant_ids))
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    ).all()
    participant_ids = [participant.id for participant in db_participants]
    user_ids = {
        participant.user_id
        for participant in db_participants
        if participant.user_id is not None
    }
    user_ids.update(
        participant.manager_user_id
        for participant in db_participants
        if participant.manager_user_id is not None
    )
    user_ids.update(
        db.session.scalars(
            select(DbNetsessionTourneyTeamMember.user_id).filter(
                DbNetsessionTourneyTeamMember.participant_id.in_(participant_ids)
            )
        ).all()
    )
    return user_ids


def get_active_user_ids_for_tournament(
    tournament_id: TournamentID,
) -> set[UserID]:
    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter_by(tournament_id=tournament_id)
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    ).all()
    participant_ids = [participant.id for participant in db_participants]
    user_ids = {
        participant.user_id
        for participant in db_participants
        if participant.user_id is not None
    }
    user_ids.update(
        participant.manager_user_id
        for participant in db_participants
        if participant.manager_user_id is not None
    )
    if participant_ids:
        user_ids.update(
            db.session.scalars(
                select(DbNetsessionTourneyTeamMember.user_id).filter(
                    DbNetsessionTourneyTeamMember.participant_id.in_(
                        participant_ids
                    )
                )
            ).all()
        )
    return user_ids

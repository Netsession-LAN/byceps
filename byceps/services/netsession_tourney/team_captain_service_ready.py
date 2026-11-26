"""
byceps.services.netsession_tourney.team_captain_service_ready
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Checks before a team captain changes the team's ready state.
"""

from __future__ import annotations

from sqlalchemy import select

from byceps.database import db

from . import domain_service
from .dbmodels import (
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyTeamMember,
)
from .models import (
    ParticipantID,
    Tournament,
)


def count_team_members(participant_id: ParticipantID) -> int:
    return int(
        db.session.scalar(
            select(db.func.count(DbNetsessionTourneyTeamMember.id)).filter_by(
                participant_id=participant_id
            )
        )
        or 0
    )


def _check_team_ready_state_change(
    tournament: Tournament, participant_id: ParticipantID, *, ready: bool
) -> str | None:
    if not ready and _is_in_bracket(participant_id):
        return (
            'Das Team steht schon im Turnierbaum und kann nicht mehr auf '
            '„nicht bereit“ gesetzt werden. Wende dich an einen Admin.'
        )

    if ready and tournament.team_size is not None:
        return _describe_incomplete_team(tournament, participant_id)

    return None


def _describe_incomplete_team(
    tournament: Tournament, participant_id: ParticipantID
) -> str | None:
    member_count = count_team_members(participant_id)
    if not domain_service.is_team_member_count_complete(
        int(member_count or 0),
        tournament.team_size,
        tournament.substitute_count,
    ):
        return (
            'Das Team ist nicht vollständig. '
            + domain_service.describe_required_team_size(
                tournament.team_size, tournament.substitute_count
            )
        )

    return None


def _is_in_bracket(participant_id: ParticipantID) -> bool:
    return (
        db.session.scalar(
            select(DbNetsessionTourneyMatchSlot.id)
            .filter_by(participant_id=participant_id)
            .limit(1)
        )
        is not None
    )

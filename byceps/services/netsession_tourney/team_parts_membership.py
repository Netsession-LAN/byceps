"""
byceps.services.netsession_tourney.team_parts_membership
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adding a user to a team participant as captain or player.
"""

from __future__ import annotations

from datetime import datetime

from byceps.database import db
from byceps.services.user.models import UserID
from byceps.util.uuid import generate_uuid7

from .dbmodels import DbNetsessionTourneyTeamMember
from .models import ParticipantID, TeamMemberID, TeamMemberRole


def add_team_member(
    participant_id: ParticipantID,
    user_id: UserID,
    role: TeamMemberRole,
    created_at: datetime,
) -> None:
    db.session.add(
        DbNetsessionTourneyTeamMember(
            TeamMemberID(generate_uuid7()),
            participant_id,
            user_id,
            role,
            created_at,
        )
    )

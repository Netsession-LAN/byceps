"""
byceps.services.netsession_tourney.registration_validation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Checks of registration mode, team size and substitutes, and of the stage types allowed for a registration mode.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

from byceps.database import db
from byceps.util.result import Err, Ok, Result

from . import domain_service
from .dbmodels import (
    DbNetsessionTourneyTeamMember,
)
from .models import (
    Participant,
    ParticipantID,
    ParticipantType,
    RegistrationMode,
    StageType,
    TeamMember,
    Tournament,
    TournamentMode,
)
from .service_helpers import (
    db_team_member_to_model,
)


def is_stage_type_compatible_with_registration_mode(
    stage_type: StageType, registration_mode: RegistrationMode
) -> bool:
    return _is_stage_type_compatible_with_registration_mode(
        stage_type, registration_mode
    )


def get_team_members_for_participants(
    participant_ids: set[ParticipantID],
) -> dict[ParticipantID, list[TeamMember]]:
    if not participant_ids:
        return {}

    db_members = db.session.scalars(
        select(DbNetsessionTourneyTeamMember).filter(
            DbNetsessionTourneyTeamMember.participant_id.in_(participant_ids)
        )
    ).all()

    members_by_participant_id: dict[ParticipantID, list[TeamMember]] = (
        defaultdict(list)
    )
    for db_member in db_members:
        members_by_participant_id[db_member.participant_id].append(
            db_team_member_to_model(db_member)
        )
    return dict(members_by_participant_id)


def validate_team_size_for_registration_mode(
    *,
    registration_mode: RegistrationMode,
    team_size: int | None,
) -> Result[None, str]:
    if team_size is None:
        return Err('Bitte eine Teamgröße angeben.')

    if team_size < 1 or team_size > 20:
        return Err('Die Teamgröße muss zwischen 1 und 20 liegen.')

    if registration_mode == RegistrationMode.solo and team_size != 1:
        return Err('Bei Einzelanmeldung muss die Teamgröße 1 sein.')

    return Ok(None)


def validate_substitute_count_for_registration_mode(
    *,
    registration_mode: RegistrationMode,
    substitute_count: int | None,
) -> Result[None, str]:
    if substitute_count is None:
        return Err('Bitte die Anzahl der Ersatzspieler angeben.')

    if substitute_count < 0 or substitute_count > 20:
        return Err(
            'Die Anzahl der Ersatzspieler muss zwischen 0 und 20 liegen.'
        )

    if registration_mode == RegistrationMode.solo and substitute_count != 0:
        return Err('Bei Einzelanmeldung gibt es keine Ersatzspieler.')

    return Ok(None)


def get_max_team_member_count(tournament: Tournament) -> int | None:
    if tournament.team_size is None:
        return None

    return tournament.team_size + (tournament.substitute_count or 0)


def validate_mode_for_registration_mode(
    *,
    mode: TournamentMode,
    registration_mode: RegistrationMode,
) -> Result[None, str]:
    _ = mode
    _ = registration_mode
    return Ok(None)


def _is_stage_type_compatible_with_registration_mode(
    stage_type: StageType,
    registration_mode: RegistrationMode,
) -> bool:
    _ = stage_type
    _ = registration_mode
    return True


def validate_bracket_ready_team_sizes(
    tournament: Tournament, participants: list[Participant]
) -> Result[None, str]:
    if tournament.team_size is None:
        return Ok(None)

    bracket_ready_teams = [
        participant
        for participant in domain_service.select_bracket_ready_participants(
            participants
        )
        if participant.type == ParticipantType.team
    ]
    if not bracket_ready_teams:
        return Ok(None)

    team_members_by_participant_id = get_team_members_for_participants(
        {participant.id for participant in bracket_ready_teams}
    )
    invalid_team_names = [
        participant.name
        for participant in bracket_ready_teams
        if not domain_service.is_team_member_count_complete(
            len(team_members_by_participant_id.get(participant.id, [])),
            tournament.team_size,
            tournament.substitute_count,
        )
    ]
    if not invalid_team_names:
        return Ok(None)

    shown_names = ', '.join(invalid_team_names[:3])
    if len(invalid_team_names) > 3:
        shown_names += ', ...'

    return Err(
        f'Diese Teams haben nicht die nötige Größe: {shown_names}. '
        + domain_service.describe_required_team_size(
            tournament.team_size, tournament.substitute_count
        )
    )

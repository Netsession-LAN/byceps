"""
byceps.services.netsession_tourney.team_captain_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Teams managed by their captain: create, update, ready state.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User, UserID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from . import domain_service
from .coin_service import (
    _charge_coins_for_tournament_registration,
)
from .dbmodels import (
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyTeamMember,
)
from .models import (
    Participant,
    ParticipantID,
    ParticipantStatus,
    ParticipantType,
    RegistrationMode,
    TeamMemberRole,
    TournamentID,
    TournamentStatus,
)
from .participant_state import (
    _refresh_match_states_for_participant_readiness,
)
from .registration_service import (
    _generate_unique_invite_code_for_tournament,
)
from .service_helpers import (
    _append_audit_log,
    _db_participant_to_model,
    _db_tournament_to_model,
)
from .team_parts_membership import add_team_member
from .tournament_queries import (
    _find_db_tournament_for_party,
    ACTIVE_PARTICIPANT_STATUS_VALUES,
)
from .tourney_registration_checks import validate_user_can_enter_tournament


def _count_team_members(participant_id: ParticipantID) -> int:
    return int(
        db.session.scalar(
            select(db.func.count(DbNetsessionTourneyTeamMember.id)).filter_by(
                participant_id=participant_id
            )
        )
        or 0
    )


def create_team_for_captain(
    party_id: PartyID,
    tournament_id: TournamentID,
    user: User,
    team_name: str,
    *,
    team_logo_url: str | None = None,
) -> Result[Participant, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.registration_mode == RegistrationMode.solo:
        return Err('Dieses Turnier erlaubt nur Solo-Anmeldungen.')

    entry_error = validate_user_can_enter_tournament(
        party_id, tournament_id, tournament, user.id, check_capacity=True
    )
    if entry_error is not None:
        return Err(entry_error)

    charge_result = _charge_coins_for_tournament_registration(
        party_id,
        tournament,
        user.id,
        created_by_user_id=user.id,
    )
    if charge_result.is_err():
        return Err(charge_result.unwrap_err())

    now = datetime.utcnow()
    invite_code = _generate_unique_invite_code_for_tournament(tournament_id)
    db_participant = DbNetsessionTourneyParticipant(
        ParticipantID(generate_uuid7()),
        tournament_id,
        ParticipantType.team,
        team_name.strip(),
        now,
        logo_url=team_logo_url.strip() if team_logo_url else None,
        manager_user_id=user.id,
        status=ParticipantStatus.forming,
        invite_code=invite_code,
    )
    db.session.add(db_participant)
    add_team_member(db_participant.id, user.id, TeamMemberRole.captain, now)

    _append_audit_log(
        actor_user_id=user.id,
        object_type='participant',
        object_id=db_participant.id,
        action='team_created',
        payload={'invite_code': invite_code},
        created_at=now,
    )
    db.session.commit()

    return Ok(_db_participant_to_model(db_participant))


def update_managed_team_for_captain(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    initiator: User,
    team_name: str,
    *,
    team_logo_url: str | None = None,
    replace_logo: bool = False,
) -> Result[Participant, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status not in {TournamentStatus.draft, TournamentStatus.live}:
        return Err('Die Teamverwaltung ist gerade nicht verfügbar.')

    db_participant = _find_db_managed_team_participant(
        party_id, tournament_id, participant_id, initiator.id
    )
    if db_participant is None:
        return Err('Team nicht gefunden, oder du darfst es nicht verwalten.')

    if tournament.status == TournamentStatus.live:
        if not replace_logo:
            return Err(
                'Während das Turnier läuft, lässt sich nur das Team-Logo ändern.'
            )

        db_participant.logo_url = (
            team_logo_url.strip() if team_logo_url else None
        )

        _append_audit_log(
            actor_user_id=initiator.id,
            object_type='participant',
            object_id=participant_id,
            action='team_logo_updated_by_captain_while_live',
            payload={
                'logo_url': db_participant.logo_url,
                'replace_logo': replace_logo,
            },
            created_at=datetime.utcnow(),
        )
        db.session.commit()

        return Ok(_db_participant_to_model(db_participant))

    team_name_clean = team_name.strip()
    if not team_name_clean:
        return Err('Ein Teamname ist erforderlich.')

    db_participant.name = team_name_clean
    if replace_logo:
        db_participant.logo_url = (
            team_logo_url.strip() if team_logo_url else None
        )

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_updated_by_captain',
        payload={
            'team_name': team_name_clean,
            'logo_url': db_participant.logo_url,
            'replace_logo': replace_logo,
        },
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(_db_participant_to_model(db_participant))


def find_managed_team_for_user(
    party_id: PartyID, tournament_id: TournamentID, user_id: UserID
) -> Participant | None:
    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return None

    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant)
        .filter_by(
            tournament_id=tournament_id,
            type=ParticipantType.team.value,
            manager_user_id=user_id,
        )
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )
    if db_participant is None:
        return None

    return _db_participant_to_model(db_participant)


def set_managed_team_ready_state(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    initiator: User,
    *,
    ready: bool,
) -> Result[Participant, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status not in {TournamentStatus.draft, TournamentStatus.live}:
        return Err(
            'Die Teamverwaltung ist gerade nicht verfügbar.'
        )

    db_participant = _find_db_managed_team_participant(
        party_id, tournament_id, participant_id, initiator.id
    )
    if db_participant is None:
        return Err('Team nicht gefunden, oder du darfst es nicht verwalten.')

    if ready and tournament.team_size is not None:
        member_count = _count_team_members(participant_id)
        if not domain_service.is_team_member_count_complete(
            int(member_count or 0),
            tournament.team_size,
            tournament.substitute_count,
        ):
            return Err(
                'Das Team ist nicht vollständig. '
                + domain_service.describe_required_team_size(
                    tournament.team_size, tournament.substitute_count
                )
            )

    db_participant.status = (
        ParticipantStatus.ready.value
        if ready
        else ParticipantStatus.forming.value
    )

    _refresh_match_states_for_participant_readiness(
        db_tournament, participant_id
    )

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_ready_state_set_by_captain',
        payload={'ready': ready},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(_db_participant_to_model(db_participant))


def _find_db_managed_team_participant(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    manager_user_id: UserID,
) -> DbNetsessionTourneyParticipant | None:
    if _find_db_tournament_for_party(party_id, tournament_id) is None:
        return None

    return db.session.scalar(
        select(DbNetsessionTourneyParticipant)
        .filter_by(
            id=participant_id,
            tournament_id=tournament_id,
            type=ParticipantType.team.value,
            manager_user_id=manager_user_id,
        )
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )

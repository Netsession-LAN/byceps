"""
byceps.services.netsession_tourney.team_invite_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Joining a team by invite code; showing and regenerating the code.
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
    DbNetsessionTourneyRegistration,
    DbNetsessionTourneyTeamMember,
)
from .eligibility import (
    validate_user_uses_ticket_for_party as _validate_user_uses_ticket_for_party,
)
from .models import (
    CoinChargeMode,
    Participant,
    ParticipantID,
    ParticipantType,
    RegistrationID,
    RegistrationMode,
    RegistrationState,
    TeamMemberID,
    TeamMemberRole,
    TournamentID,
    TournamentStatus,
)
from .participant_state import (
    _is_user_already_active_participant,
)
from .registration_service import (
    _generate_unique_invite_code_for_tournament,
)
from .registration_validation import (
    _get_max_team_member_count,
)
from .service_helpers import (
    _append_audit_log,
    _db_participant_to_model,
    _db_tournament_to_model,
)
from .team_captain_service import (
    _count_team_members,
    _find_db_managed_team_participant,
)
from .tournament_queries import (
    _find_db_tournament_for_party,
    ACTIVE_PARTICIPANT_STATUS_VALUES,
)


def join_team_by_invite_code(
    party_id: PartyID,
    tournament_id: TournamentID,
    invite_code: str,
    user: User,
) -> Result[Participant, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.registration_mode == RegistrationMode.solo:
        return Err('Dieses Turnier erlaubt nur Solo-Anmeldungen.')

    validation_result = domain_service.validate_registration_open(
        tournament, datetime.utcnow()
    )
    if validation_result.is_err():
        return Err(validation_result.unwrap_err())

    ticket_validation_result = _validate_user_uses_ticket_for_party(
        user.id, party_id
    )
    if ticket_validation_result.is_err():
        return Err(ticket_validation_result.unwrap_err())

    if _is_user_already_active_participant(tournament_id, user.id):
        return Err('Du bist in diesem Turnier bereits aktiv angemeldet.')

    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant).filter_by(
            tournament_id=tournament_id,
            invite_code=invite_code.strip(),
            type=ParticipantType.team.value,
        )
    )
    if db_participant is None:
        return Err('Unbekannter Invite-Code.')
    if db_participant.status not in ACTIVE_PARTICIPANT_STATUS_VALUES:
        return Err('Diesem Team kann man nicht beitreten.')
    max_team_member_count = _get_max_team_member_count(tournament)
    if max_team_member_count is not None:
        member_count = _count_team_members(db_participant.id)
    if int(member_count or 0) >= max_team_member_count:
        return Err('Dieses Team ist bereits voll.')

    if tournament.coin_charge_mode == CoinChargeMode.all_members:
        charge_result = _charge_coins_for_tournament_registration(
            party_id,
            tournament,
            user.id,
            created_by_user_id=user.id,
        )
        if charge_result.is_err():
            return Err(charge_result.unwrap_err())

    registration = db.session.scalar(
        select(DbNetsessionTourneyRegistration).filter_by(
            tournament_id=tournament_id, user_id=user.id
        )
    )
    if registration is None:
        db.session.add(
            DbNetsessionTourneyRegistration(
                RegistrationID(generate_uuid7()),
                tournament_id,
                user.id,
                RegistrationState.registered,
                datetime.utcnow(),
            )
        )
    else:
        registration.state = RegistrationState.registered.value

    db.session.add(
        DbNetsessionTourneyTeamMember(
            TeamMemberID(generate_uuid7()),
            db_participant.id,
            user.id,
            TeamMemberRole.player,
            datetime.utcnow(),
        )
    )
    db.session.commit()

    return Ok(_db_participant_to_model(db_participant))


def get_team_invite_code_for_manager(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    manager_user_id: UserID,
) -> Result[str, str]:
    db_participant = _find_db_managed_team_participant(
        party_id, tournament_id, participant_id, manager_user_id
    )
    if db_participant is None:
        return Err('Team nicht gefunden, oder du darfst es nicht verwalten.')

    if not db_participant.invite_code:
        return Err('Für dieses Team gibt es keinen Einladungscode.')

    return Ok(db_participant.invite_code)


def regenerate_team_invite_code_for_manager(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    initiator: User,
) -> Result[str, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status != TournamentStatus.draft:
        return Err(
            'Teams lassen sich nur im Entwurf verwalten.'
        )

    db_participant = _find_db_managed_team_participant(
        party_id, tournament_id, participant_id, initiator.id
    )
    if db_participant is None:
        return Err('Team nicht gefunden, oder du darfst es nicht verwalten.')

    invite_code = _generate_unique_invite_code_for_tournament(tournament_id)
    db_participant.invite_code = invite_code

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_invite_code_regenerated',
        payload={},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(invite_code)

"""
byceps.services.netsession_tourney.registration_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Registration and deregistration of players and teams.
"""

from __future__ import annotations

from datetime import datetime
import secrets

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User, UserID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from . import domain_service
from .coin_service import (
    _charge_coins_for_tournament_registration,
    _refund_coins_for_tournament_registration_if_available,
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
    Participant,
    ParticipantID,
    ParticipantStatus,
    ParticipantType,
    RegistrationID,
    RegistrationMode,
    RegistrationState,
    TeamMemberID,
    TeamMemberRole,
    TournamentID,
    TournamentStatus,
)
from .notification_service import (
    _append_notification,
)
from .participant_state import (
    _find_db_active_participant_for_user,
    _is_tournament_full,
    _is_user_already_active_participant,
    count_active_participants_for_tournament,
)
from .service_helpers import (
    _append_audit_log,
    _db_participant_to_model,
    _db_tournament_to_model,
)
from .team_coins_and_readiness import (
    reset_ready_if_incomplete,
)
from .tournament_queries import (
    _find_db_tournament_for_party,
)


def register_user(
    party_id: PartyID, tournament_id: TournamentID, user: User
) -> Result[Participant, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.registration_mode in {
        RegistrationMode.team_captain_managed,
        RegistrationMode.team_preformed_only,
    }:
        return Err(
            'Dieses Turnier nutzt Team-Anmeldungen. Bitte erstelle ein Team oder trete einem Team bei.'
        )

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

    active_participant_count = count_active_participants_for_tournament(
        party_id, tournament_id
    )
    if _is_tournament_full(tournament, active_participant_count):
        return Err('Das Turnier ist voll.')

    charge_result = _charge_coins_for_tournament_registration(
        party_id,
        tournament,
        user.id,
        created_by_user_id=user.id,
    )
    if charge_result.is_err():
        return Err(charge_result.unwrap_err())

    now = datetime.utcnow()
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
                now,
            )
        )
    else:
        registration.state = RegistrationState.registered.value

    if tournament.registration_mode in {
        RegistrationMode.solo,
        RegistrationMode.mixed,
    }:
        participant_type = ParticipantType.user
        participant_status = ParticipantStatus.ready
    else:
        participant_type = ParticipantType.team
        participant_status = ParticipantStatus.forming
    db_participant = DbNetsessionTourneyParticipant(
        ParticipantID(generate_uuid7()),
        tournament_id,
        participant_type,
        user.screen_name or str(user.id),
        now,
        user_id=user.id if participant_type == ParticipantType.user else None,
        manager_user_id=user.id,
        status=participant_status,
        invite_code=(
            _generate_unique_invite_code_for_tournament(tournament_id)
            if participant_type == ParticipantType.team
            else None
        ),
    )
    db.session.add(db_participant)

    if participant_type == ParticipantType.team:
        db.session.add(
            DbNetsessionTourneyTeamMember(
                TeamMemberID(generate_uuid7()),
                db_participant.id,
                user.id,
                TeamMemberRole.captain,
                now,
            )
        )

    _append_notification(
        tournament_id=tournament_id,
        user_id=user.id,
        kind='registration_created',
        payload={'participant_id': str(db_participant.id)},
        created_at=now,
    )
    _append_audit_log(
        actor_user_id=user.id,
        object_type='participant',
        object_id=db_participant.id,
        action='participant_registered',
        payload={'tournament_id': str(tournament_id)},
        created_at=now,
    )

    db.session.commit()
    return Ok(_db_participant_to_model(db_participant))


def deregister_user(
    party_id: PartyID, tournament_id: TournamentID, user: User
) -> Result[None, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status == TournamentStatus.closed:
        return Err(
            'Eine Abmeldung ist nicht mehr möglich, da das Turnier geschlossen ist.'
        )

    if tournament.status == TournamentStatus.canceled:
        return Err(
            'Eine Abmeldung ist nicht mehr möglich, da das Turnier abgesagt ist.'
        )

    if tournament.status != TournamentStatus.draft:
        return Err(
            'Eine Abmeldung ist nicht mehr möglich, da das Turnier bereits live ist.'
        )

    db_participant = _find_db_active_participant_for_user(
        tournament_id, user.id
    )
    if db_participant is None:
        return Err('Du bist für dieses Turnier nicht angemeldet.')

    now = datetime.utcnow()

    # Solo participant: drop the entry and cancel registration.
    if db_participant.type == ParticipantType.user.value:
        db_participant.status = ParticipantStatus.dropped.value
        _set_registration_state_for_user(
            tournament_id, user.id, RegistrationState.canceled
        )
        _refund_coins_for_tournament_registration_if_available(
            party_id,
            tournament,
            user.id,
            created_by_user_id=user.id,
        )
        _append_audit_log(
            actor_user_id=user.id,
            object_type='participant',
            object_id=db_participant.id,
            action='participant_deregistered',
            payload={'reason_code': 'self_deregister'},
            created_at=now,
        )
        db.session.commit()
        return Ok(None)

    # Team participant.
    if db_participant.manager_user_id == user.id:
        # Captain leaving: drop whole team from this tournament.
        db_participant.status = ParticipantStatus.dropped.value
        member_user_ids = _get_team_member_user_ids_for_participant(
            db_participant.id
        )
        for member_user_id in member_user_ids:
            _set_registration_state_for_user(
                tournament_id, member_user_id, RegistrationState.canceled
            )
            _refund_coins_for_tournament_registration_if_available(
                party_id, tournament, member_user_id, created_by_user_id=user.id
            )
        _append_audit_log(
            actor_user_id=user.id,
            object_type='participant',
            object_id=db_participant.id,
            action='team_deregistered_by_captain',
            payload={'reason_code': 'captain_deregister'},
            created_at=now,
        )
        db.session.commit()
        return Ok(None)

    # Non-captain team member: remove membership only.
    db_member = db.session.scalar(
        select(DbNetsessionTourneyTeamMember).filter_by(
            participant_id=db_participant.id,
            user_id=user.id,
        )
    )
    if db_member is None:
        return Err('Du bist für dieses Turnier nicht angemeldet.')

    db.session.delete(db_member)
    _set_registration_state_for_user(
        tournament_id, user.id, RegistrationState.canceled
    )
    _refund_coins_for_tournament_registration_if_available(
        party_id, tournament, user.id, created_by_user_id=user.id
    )
    reset_ready_if_incomplete(db_participant, tournament.team_size)
    _append_audit_log(
        actor_user_id=user.id,
        object_type='participant',
        object_id=db_participant.id,
        action='team_member_left',
        payload={'member_user_id': str(user.id)},
        created_at=now,
    )
    db.session.commit()
    return Ok(None)


def _set_registration_state_for_user(
    tournament_id: TournamentID, user_id: UserID, state: RegistrationState
) -> None:
    db_registration = db.session.scalar(
        select(DbNetsessionTourneyRegistration).filter_by(
            tournament_id=tournament_id, user_id=user_id
        )
    )
    if db_registration is None:
        return

    db_registration.state = state.value


def _ensure_registration_is_registered(
    tournament_id: TournamentID, user_id: UserID
) -> None:
    db_registration = db.session.scalar(
        select(DbNetsessionTourneyRegistration).filter_by(
            tournament_id=tournament_id,
            user_id=user_id,
        )
    )
    if db_registration is None:
        db.session.add(
            DbNetsessionTourneyRegistration(
                RegistrationID(generate_uuid7()),
                tournament_id,
                user_id,
                RegistrationState.registered,
                datetime.utcnow(),
            )
        )
        return

    db_registration.state = RegistrationState.registered.value


def _get_team_member_user_ids_for_participant(
    participant_id: ParticipantID,
) -> list[UserID]:
    return db.session.scalars(
        select(DbNetsessionTourneyTeamMember.user_id).filter_by(
            participant_id=participant_id
        )
    ).all()


def _generate_unique_invite_code_for_tournament(
    tournament_id: TournamentID,
) -> str:
    for _ in range(64):
        # Use strong random bytes instead of UUIDv7 prefix (timestamp-heavy),
        # which can collide frequently for short invite codes.
        invite_code = secrets.token_hex(4)
        existing_participant_id = db.session.scalar(
            select(DbNetsessionTourneyParticipant.id).filter_by(
                tournament_id=tournament_id, invite_code=invite_code
            )
        )
        if existing_participant_id is None:
            return invite_code

    raise RuntimeError(
        'Could not generate unique invite code after 64 attempts.'
    )

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

from .coin_service import (
    charge_coins_for_tournament_registration,
    refund_coins_for_tournament_registration_if_available,
)
from .dbmodels import (
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyRegistration,
    DbNetsessionTourneyTeamMember,
)
from .models import (
    Participant,
    ParticipantID,
    ParticipantStatus,
    ParticipantType,
    RegistrationID,
    RegistrationMode,
    RegistrationState,
    TeamMemberRole,
    Tournament,
    TournamentID,
    TournamentStatus,
)
from .notification_service import (
    append_notification,
)
from .participant_state import (
    find_db_active_participant_for_user,
)
from .service_helpers import (
    append_audit_log,
    db_participant_to_model,
    db_tournament_to_model,
)
from .team_coins_and_readiness import (
    reset_ready_if_incomplete,
)
from .team_parts_membership import add_team_member
from .tournament_queries import (
    find_db_tournament_for_party,
)
from .tourney_registration_checks import validate_user_can_enter_tournament


def register_user(
    party_id: PartyID, tournament_id: TournamentID, user: User
) -> Result[Participant, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = db_tournament_to_model(db_tournament)
    if tournament.registration_mode in {
        RegistrationMode.team_captain_managed,
        RegistrationMode.team_preformed_only,
    }:
        return Err(
            'Dieses Turnier nutzt Team-Anmeldungen. Bitte erstelle ein Team oder trete einem Team bei.'
        )

    entry_error = validate_user_can_enter_tournament(
        party_id, tournament_id, tournament, user.id, check_capacity=True
    )
    if entry_error is not None:
        return Err(entry_error)

    charge_result = charge_coins_for_tournament_registration(
        party_id,
        tournament,
        user.id,
        created_by_user_id=user.id,
    )
    if charge_result.is_err():
        return Err(charge_result.unwrap_err())

    now = datetime.utcnow()
    ensure_registration_is_registered(tournament_id, user.id, created_at=now)
    db_participant = _add_participant_for_registering_user(
        tournament_id, tournament, user, now
    )

    append_notification(
        tournament_id=tournament_id,
        user_id=user.id,
        kind='registration_created',
        payload={'participant_id': str(db_participant.id)},
        created_at=now,
    )
    append_audit_log(
        actor_user_id=user.id,
        object_type='participant',
        object_id=db_participant.id,
        action='participant_registered',
        payload={'tournament_id': str(tournament_id)},
        created_at=now,
    )

    db.session.commit()
    return Ok(db_participant_to_model(db_participant))


def _add_participant_for_registering_user(
    tournament_id: TournamentID,
    tournament: Tournament,
    user: User,
    now: datetime,
) -> DbNetsessionTourneyParticipant:
    """Add a solo participant, or a forming team with the user as captain."""
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
            generate_unique_invite_code_for_tournament(tournament_id)
            if participant_type == ParticipantType.team
            else None
        ),
    )
    db.session.add(db_participant)

    if participant_type == ParticipantType.team:
        add_team_member(db_participant.id, user.id, TeamMemberRole.captain, now)

    return db_participant


def deregister_user(
    party_id: PartyID, tournament_id: TournamentID, user: User
) -> Result[None, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = db_tournament_to_model(db_tournament)
    status_error = _get_deregistration_status_error(tournament)
    if status_error is not None:
        return Err(status_error)

    db_participant = find_db_active_participant_for_user(tournament_id, user.id)
    if db_participant is None:
        return Err('Du bist für dieses Turnier nicht angemeldet.')

    now = datetime.utcnow()

    # Solo participant: drop the entry and cancel registration.
    if db_participant.type == ParticipantType.user.value:
        _deregister_solo_participant(
            party_id, tournament_id, tournament, db_participant, user, now
        )
        return Ok(None)

    # Team participant.
    if db_participant.manager_user_id == user.id:
        # Captain leaving: drop whole team from this tournament.
        _deregister_team_by_captain(
            party_id, tournament_id, tournament, db_participant, user, now
        )
        return Ok(None)

    # Non-captain team member: remove membership only.
    return _leave_team_as_member(
        party_id, tournament_id, tournament, db_participant, user, now
    )


def _get_deregistration_status_error(tournament: Tournament) -> str | None:
    if tournament.status == TournamentStatus.closed:
        return 'Eine Abmeldung ist nicht mehr möglich, da das Turnier geschlossen ist.'

    if tournament.status == TournamentStatus.canceled:
        return 'Eine Abmeldung ist nicht mehr möglich, da das Turnier abgesagt ist.'

    if tournament.status != TournamentStatus.draft:
        return 'Eine Abmeldung ist nicht mehr möglich, da das Turnier bereits live ist.'

    return None


def _deregister_solo_participant(
    party_id: PartyID,
    tournament_id: TournamentID,
    tournament: Tournament,
    db_participant: DbNetsessionTourneyParticipant,
    user: User,
    now: datetime,
) -> None:
    db_participant.status = ParticipantStatus.dropped.value
    set_registration_state_for_user(
        tournament_id, user.id, RegistrationState.canceled
    )
    refund_coins_for_tournament_registration_if_available(
        party_id,
        tournament,
        user.id,
        created_by_user_id=user.id,
    )
    append_audit_log(
        actor_user_id=user.id,
        object_type='participant',
        object_id=db_participant.id,
        action='participant_deregistered',
        payload={'reason_code': 'self_deregister'},
        created_at=now,
    )
    db.session.commit()


def _deregister_team_by_captain(
    party_id: PartyID,
    tournament_id: TournamentID,
    tournament: Tournament,
    db_participant: DbNetsessionTourneyParticipant,
    user: User,
    now: datetime,
) -> None:
    db_participant.status = ParticipantStatus.dropped.value
    member_user_ids = get_team_member_user_ids_for_participant(
        db_participant.id
    )
    for member_user_id in member_user_ids:
        set_registration_state_for_user(
            tournament_id, member_user_id, RegistrationState.canceled
        )
        refund_coins_for_tournament_registration_if_available(
            party_id, tournament, member_user_id, created_by_user_id=user.id
        )
    append_audit_log(
        actor_user_id=user.id,
        object_type='participant',
        object_id=db_participant.id,
        action='team_deregistered_by_captain',
        payload={'reason_code': 'captain_deregister'},
        created_at=now,
    )
    db.session.commit()


def _leave_team_as_member(
    party_id: PartyID,
    tournament_id: TournamentID,
    tournament: Tournament,
    db_participant: DbNetsessionTourneyParticipant,
    user: User,
    now: datetime,
) -> Result[None, str]:
    db_member = db.session.scalar(
        select(DbNetsessionTourneyTeamMember).filter_by(
            participant_id=db_participant.id,
            user_id=user.id,
        )
    )
    if db_member is None:
        return Err('Du bist für dieses Turnier nicht angemeldet.')

    db.session.delete(db_member)
    set_registration_state_for_user(
        tournament_id, user.id, RegistrationState.canceled
    )
    refund_coins_for_tournament_registration_if_available(
        party_id, tournament, user.id, created_by_user_id=user.id
    )
    reset_ready_if_incomplete(
        db_participant, tournament.team_size, tournament.substitute_count
    )
    append_audit_log(
        actor_user_id=user.id,
        object_type='participant',
        object_id=db_participant.id,
        action='team_member_left',
        payload={'member_user_id': str(user.id)},
        created_at=now,
    )
    db.session.commit()
    return Ok(None)


def set_registration_state_for_user(
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


def ensure_registration_is_registered(
    tournament_id: TournamentID,
    user_id: UserID,
    *,
    created_at: datetime | None = None,
) -> None:
    """Create the registration as registered, or set an existing one to
    registered. A new registration is created at `created_at` (default:
    now)."""
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
                created_at if created_at is not None else datetime.utcnow(),
            )
        )
        return

    db_registration.state = RegistrationState.registered.value


def get_team_member_user_ids_for_participant(
    participant_id: ParticipantID,
) -> list[UserID]:
    return db.session.scalars(
        select(DbNetsessionTourneyTeamMember.user_id).filter_by(
            participant_id=participant_id
        )
    ).all()


def generate_unique_invite_code_for_tournament(
    tournament_id: TournamentID,
) -> str:
    for _ in range(64):
        # Use strong random bytes instead of UUIDv7 prefix (timestamp-heavy),
        # which can collide frequently for short invite codes.
        invite_code = secrets.token_hex(6)  # 48 bits
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

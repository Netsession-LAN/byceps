"""
byceps.services.netsession_tourney.team_admin_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Team management by tournament admins.
"""

from __future__ import annotations

from datetime import datetime

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
    DbNetsessionTourneyTeamMember,
)
from .models import (
    CoinChargeMode,
    Participant,
    ParticipantID,
    ParticipantStatus,
    ParticipantType,
    RegistrationState,
    TeamMemberID,
    TeamMemberRole,
    Tournament,
    TournamentID,
    TournamentStatus,
)
from .registration_service import (
    ensure_registration_is_registered,
    generate_unique_invite_code_for_tournament,
    set_registration_state_for_user,
)
from .service_helpers import (
    append_audit_log,
    db_participant_to_model,
    db_tournament_to_model,
)
from .team_admin_checks import (
    _check_team_admin_tournament_state,
    _check_team_member_addable_by_admin,
    _check_team_registration_by_admin,
)
from .team_coins_and_readiness import (
    reset_ready_if_incomplete,
)
from .tournament_queries import (
    ACTIVE_PARTICIPANT_STATUS_VALUES,
    find_db_tournament_for_party,
)


def create_team_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    team_name: str,
    captain_user: User,
    initiator: User,
    *,
    team_logo_url: str | None = None,
) -> Result[Participant, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = db_tournament_to_model(db_tournament)
    state_error = _check_team_admin_tournament_state(tournament)
    if state_error is not None:
        return Err(state_error)
    registration_check = _check_team_registration_by_admin(
        party_id, tournament_id, tournament, captain_user.id
    )
    if registration_check.is_err():
        return registration_check

    charge_result = charge_coins_for_tournament_registration(
        party_id,
        tournament,
        captain_user.id,
        created_by_user_id=initiator.id,
    )
    if charge_result.is_err():
        return Err(charge_result.unwrap_err())

    now = datetime.utcnow()
    invite_code = generate_unique_invite_code_for_tournament(tournament_id)
    db_participant = DbNetsessionTourneyParticipant(
        ParticipantID(generate_uuid7()),
        tournament_id,
        ParticipantType.team,
        team_name.strip(),
        now,
        logo_url=team_logo_url.strip() if team_logo_url else None,
        manager_user_id=captain_user.id,
        status=ParticipantStatus.forming,
        invite_code=invite_code,
    )
    db.session.add(db_participant)
    db.session.add(
        DbNetsessionTourneyTeamMember(
            TeamMemberID(generate_uuid7()),
            db_participant.id,
            captain_user.id,
            TeamMemberRole.captain,
            now,
        )
    )
    ensure_registration_is_registered(tournament_id, captain_user.id)

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=db_participant.id,
        action='team_created_by_admin',
        payload={'captain_user_id': str(captain_user.id)},
        created_at=now,
    )
    db.session.commit()

    return Ok(db_participant_to_model(db_participant))


def add_team_member_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    member_user: User,
    initiator: User,
) -> Result[None, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = db_tournament_to_model(db_tournament)
    state_error = _check_team_admin_tournament_state(tournament)
    if state_error is not None:
        return Err(state_error)

    db_participant = _find_active_db_team(participant_id, tournament_id)
    if db_participant is None:
        return Err('Unbekanntes Team.')

    member_check = _check_team_member_addable_by_admin(
        party_id, tournament_id, tournament, participant_id, member_user.id
    )
    if member_check.is_err():
        return member_check

    charge_result = _charge_team_member_coins_if_required(
        party_id, tournament, member_user, initiator
    )
    if charge_result.is_err():
        return charge_result

    db.session.add(
        DbNetsessionTourneyTeamMember(
            TeamMemberID(generate_uuid7()),
            participant_id,
            member_user.id,
            TeamMemberRole.player,
            datetime.utcnow(),
        )
    )
    ensure_registration_is_registered(tournament_id, member_user.id)

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_member_added_by_admin',
        payload={'member_user_id': str(member_user.id)},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(None)


def remove_team_member_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    member_user_id: UserID,
    initiator: User,
) -> Result[None, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = db_tournament_to_model(db_tournament)
    if tournament.status != TournamentStatus.draft:
        return Err('Teilnehmer lassen sich nur im Entwurf verwalten.')

    db_participant = db.session.scalar(
        select(DbNetsessionTourneyParticipant)
        .filter_by(
            id=participant_id,
            tournament_id=tournament_id,
            type=ParticipantType.team.value,
        )
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )
    if db_participant is None:
        return Err('Unbekanntes Team.')

    db_member = db.session.scalar(
        select(DbNetsessionTourneyTeamMember).filter_by(
            participant_id=participant_id,
            user_id=member_user_id,
        )
    )
    if db_member is None:
        return Err('Unbekanntes Teammitglied.')
    if db_member.role == TeamMemberRole.captain.value:
        return Err('Der Captain kann nicht aus dem Team entfernt werden.')

    db.session.delete(db_member)
    set_registration_state_for_user(
        tournament_id, member_user_id, RegistrationState.canceled
    )
    refund_coins_for_tournament_registration_if_available(
        party_id, tournament, member_user_id, created_by_user_id=initiator.id
    )
    reset_ready_if_incomplete(
        db_participant, tournament.team_size, tournament.substitute_count
    )
    append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_member_removed_by_admin',
        payload={'member_user_id': str(member_user_id)},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(None)


def assign_team_captain_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    member_user_id: UserID,
    initiator: User,
) -> Result[None, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = db_tournament_to_model(db_tournament)
    state_error = _check_team_admin_tournament_state(tournament)
    if state_error is not None:
        return Err(state_error)

    db_participant = _find_active_db_team(participant_id, tournament_id)
    if db_participant is None:
        return Err('Unbekanntes Team.')

    if db_participant.manager_user_id == member_user_id:
        return Ok(None)

    members_result = _find_captain_swap_members(participant_id, member_user_id)
    if members_result.is_err():
        return Err(members_result.unwrap_err())
    db_member, db_current_captain_member = members_result.unwrap()

    old_captain_user_id = db_participant.manager_user_id
    db_current_captain_member.role = TeamMemberRole.player.value
    db_member.role = TeamMemberRole.captain.value
    db_participant.manager_user_id = member_user_id

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_captain_changed_by_admin',
        payload=_build_captain_change_payload(
            old_captain_user_id, member_user_id
        ),
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(None)


def _find_active_db_team(
    participant_id: ParticipantID, tournament_id: TournamentID
) -> DbNetsessionTourneyParticipant | None:
    return db.session.scalar(
        select(DbNetsessionTourneyParticipant)
        .filter_by(
            id=participant_id,
            tournament_id=tournament_id,
            type=ParticipantType.team.value,
        )
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    )


def _charge_team_member_coins_if_required(
    party_id: PartyID,
    tournament: Tournament,
    member_user: User,
    initiator: User,
) -> Result[None, str]:
    if tournament.coin_charge_mode != CoinChargeMode.all_members:
        return Ok(None)

    charge_result = charge_coins_for_tournament_registration(
        party_id,
        tournament,
        member_user.id,
        created_by_user_id=initiator.id,
    )
    if charge_result.is_err():
        return Err(charge_result.unwrap_err())

    return Ok(None)


def _find_captain_swap_members(
    participant_id: ParticipantID, member_user_id: UserID
) -> Result[
    tuple[DbNetsessionTourneyTeamMember, DbNetsessionTourneyTeamMember], str
]:
    db_member = db.session.scalar(
        select(DbNetsessionTourneyTeamMember).filter_by(
            participant_id=participant_id,
            user_id=member_user_id,
        )
    )
    if db_member is None:
        return Err('Unbekanntes Teammitglied.')

    db_current_captain_member = db.session.scalar(
        select(DbNetsessionTourneyTeamMember).filter_by(
            participant_id=participant_id,
            role=TeamMemberRole.captain.value,
        )
    )
    if db_current_captain_member is None:
        return Err('Der aktuelle Captain ließ sich nicht ermitteln.')

    return Ok((db_member, db_current_captain_member))


def _build_captain_change_payload(
    old_captain_user_id: UserID | None, new_captain_user_id: UserID
) -> dict[str, str | None]:
    return {
        'old_captain_user_id': (
            str(old_captain_user_id) if old_captain_user_id else None
        ),
        'new_captain_user_id': str(new_captain_user_id),
    }

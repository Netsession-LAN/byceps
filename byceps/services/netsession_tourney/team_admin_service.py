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
    _charge_coins_for_tournament_registration,
    _refund_coins_for_tournament_registration_if_available,
)
from .dbmodels import (
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyTeamMember,
)
from .eligibility import (
    validate_user_uses_ticket_for_party as _validate_user_uses_ticket_for_party,
)
from .models import (
    CoinChargeMode,
    Participant,
    ParticipantID,
    ParticipantStatus,
    ParticipantType,
    RegistrationMode,
    RegistrationState,
    TeamMemberID,
    TeamMemberRole,
    TournamentID,
    TournamentStatus,
)
from .participant_state import (
    _is_user_already_active_participant,
    count_active_participants_for_tournament,
)
from .registration_service import (
    _ensure_registration_is_registered,
    _generate_unique_invite_code_for_tournament,
    _set_registration_state_for_user,
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
)
from .team_coins_and_readiness import (
    reset_ready_if_incomplete,
)
from .tournament_queries import (
    _find_db_tournament_for_party,
    ACTIVE_PARTICIPANT_STATUS_VALUES,
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
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status != TournamentStatus.draft:
        return Err(
            'Teilnehmer lassen sich nur im Entwurf verwalten.'
        )
    if tournament.registration_mode == RegistrationMode.solo:
        return Err('Bei Einzelanmeldung gibt es keine Teamverwaltung.')
    if (ticket_check := _validate_user_uses_ticket_for_party(captain_user.id, party_id)).is_err():
        return ticket_check
    if _is_user_already_active_participant(tournament_id, captain_user.id):
        return Err('Du bist in diesem Turnier bereits aktiv angemeldet.')

    if tournament.participant_limit is not None:
        active_count = count_active_participants_for_tournament(
            party_id, tournament_id
        )
        if active_count >= tournament.participant_limit:
            return Err('Das Turnier ist voll.')

    charge_result = _charge_coins_for_tournament_registration(
        party_id,
        tournament,
        captain_user.id,
        created_by_user_id=initiator.id,
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
    _ensure_registration_is_registered(tournament_id, captain_user.id)

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=db_participant.id,
        action='team_created_by_admin',
        payload={'captain_user_id': str(captain_user.id)},
        created_at=now,
    )
    db.session.commit()

    return Ok(_db_participant_to_model(db_participant))


def add_team_member_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    member_user: User,
    initiator: User,
) -> Result[None, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status != TournamentStatus.draft:
        return Err(
            'Teilnehmer lassen sich nur im Entwurf verwalten.'
        )
    if tournament.registration_mode == RegistrationMode.solo:
        return Err('Bei Einzelanmeldung gibt es keine Teamverwaltung.')

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

    if (ticket_check := _validate_user_uses_ticket_for_party(member_user.id, party_id)).is_err():
        return ticket_check
    if _is_user_already_active_participant(tournament_id, member_user.id):
        return Err('Du bist in diesem Turnier bereits aktiv angemeldet.')

    max_team_member_count = _get_max_team_member_count(tournament)
    if max_team_member_count is not None:
        member_count = _count_team_members(participant_id)
        if int(member_count or 0) >= max_team_member_count:
            return Err('Dieses Team ist bereits voll.')

    if tournament.coin_charge_mode == CoinChargeMode.all_members:
        charge_result = _charge_coins_for_tournament_registration(
            party_id,
            tournament,
            member_user.id,
            created_by_user_id=initiator.id,
        )
        if charge_result.is_err():
            return Err(charge_result.unwrap_err())

    db.session.add(
        DbNetsessionTourneyTeamMember(
            TeamMemberID(generate_uuid7()),
            participant_id,
            member_user.id,
            TeamMemberRole.player,
            datetime.utcnow(),
        )
    )
    _ensure_registration_is_registered(tournament_id, member_user.id)

    _append_audit_log(
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
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status != TournamentStatus.draft:
        return Err(
            'Teilnehmer lassen sich nur im Entwurf verwalten.'
        )

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
    _set_registration_state_for_user(
        tournament_id, member_user_id, RegistrationState.canceled
    )
    _refund_coins_for_tournament_registration_if_available(
        party_id, tournament, member_user_id, created_by_user_id=initiator.id
    )
    reset_ready_if_incomplete(
        db_participant, tournament.team_size, tournament.substitute_count
    )
    _append_audit_log(
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
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = _db_tournament_to_model(db_tournament)
    if tournament.status != TournamentStatus.draft:
        return Err(
            'Teilnehmer lassen sich nur im Entwurf verwalten.'
        )
    if tournament.registration_mode == RegistrationMode.solo:
        return Err('Bei Einzelanmeldung gibt es keine Teamverwaltung.')

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

    if db_participant.manager_user_id == member_user_id:
        return Ok(None)

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

    old_captain_user_id = db_participant.manager_user_id
    db_current_captain_member.role = TeamMemberRole.player.value
    db_member.role = TeamMemberRole.captain.value
    db_participant.manager_user_id = member_user_id

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_captain_changed_by_admin',
        payload={
            'old_captain_user_id': (
                str(old_captain_user_id) if old_captain_user_id else None
            ),
            'new_captain_user_id': str(member_user_id),
        },
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(None)

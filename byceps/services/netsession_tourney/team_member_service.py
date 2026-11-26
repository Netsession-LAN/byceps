"""
byceps.services.netsession_tourney.team_member_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Members of a captain-managed team: add, remove, hand over the captaincy.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User, UserID
from byceps.util.result import Err, Ok, Result

from .coin_service import (
    charge_coins_for_tournament_registration,
    refund_coins_for_tournament_registration_if_available,
)
from .dbmodels import (
    DbNetsessionTourneyTeamMember,
)
from .eligibility import (
    validate_user_uses_ticket_for_party as _validate_user_uses_ticket_for_party,
)
from .models import (
    CoinChargeMode,
    ParticipantID,
    RegistrationState,
    TeamMemberRole,
    TournamentID,
    TournamentStatus,
)
from .participant_state import (
    is_user_already_active_participant,
)
from .registration_service import (
    ensure_registration_is_registered,
    set_registration_state_for_user,
)
from .registration_validation import (
    get_max_team_member_count,
)
from .service_helpers import (
    append_audit_log,
    db_tournament_to_model,
)
from .team_captain_service import (
    count_team_members,
    find_db_managed_team_participant,
)
from .team_coins_and_readiness import (
    reset_ready_if_incomplete,
)
from .team_parts_membership import add_team_member
from .tournament_queries import (
    find_db_tournament_for_party,
)


def add_team_member_by_captain(
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
    if tournament.status != TournamentStatus.draft:
        return Err('Teams lassen sich nur im Entwurf verwalten.')

    db_participant = find_db_managed_team_participant(
        party_id, tournament_id, participant_id, initiator.id
    )
    if db_participant is None:
        return Err('Team nicht gefunden, oder du darfst es nicht verwalten.')

    ticket_validation_result = _validate_user_uses_ticket_for_party(
        member_user.id, party_id
    )
    if ticket_validation_result.is_err():
        return Err(ticket_validation_result.unwrap_err())

    if is_user_already_active_participant(tournament_id, member_user.id):
        return Err('Du bist in diesem Turnier bereits aktiv angemeldet.')

    max_team_member_count = get_max_team_member_count(tournament)
    if max_team_member_count is not None:
        member_count = count_team_members(participant_id)
        if int(member_count or 0) >= max_team_member_count:
            return Err('Dieses Team ist bereits voll.')

    if tournament.coin_charge_mode == CoinChargeMode.all_members:
        charge_result = charge_coins_for_tournament_registration(
            party_id,
            tournament,
            member_user.id,
            created_by_user_id=initiator.id,
        )
        if charge_result.is_err():
            return Err(charge_result.unwrap_err())

    ensure_registration_is_registered(tournament_id, member_user.id)
    add_team_member(
        participant_id, member_user.id, TeamMemberRole.player, datetime.utcnow()
    )

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_member_added_by_captain',
        payload={'member_user_id': str(member_user.id)},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(None)


def assign_team_captain_by_captain(
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
        return Err('Teams lassen sich nur im Entwurf verwalten.')

    db_participant = find_db_managed_team_participant(
        party_id, tournament_id, participant_id, initiator.id
    )
    if db_participant is None:
        return Err('Team nicht gefunden, oder du darfst es nicht verwalten.')

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

    db_current_captain_member.role = TeamMemberRole.player.value
    db_member.role = TeamMemberRole.captain.value
    db_participant.manager_user_id = member_user_id

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_captain_changed_by_captain',
        payload={
            'old_captain_user_id': str(initiator.id),
            'new_captain_user_id': str(member_user_id),
        },
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(None)


def remove_team_member_by_captain(
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
        return Err('Teams lassen sich nur im Entwurf verwalten.')

    db_participant = find_db_managed_team_participant(
        party_id, tournament_id, participant_id, initiator.id
    )
    if db_participant is None:
        return Err('Team nicht gefunden, oder du darfst es nicht verwalten.')

    db_member = db.session.scalar(
        select(DbNetsessionTourneyTeamMember).filter_by(
            participant_id=participant_id,
            user_id=member_user_id,
        )
    )
    if db_member is None:
        return Err('Unbekanntes Teammitglied.')
    if db_member.role == TeamMemberRole.captain.value:
        return Err(
            'Du kannst dich als Captain nicht selbst aus dem Team entfernen.'
        )

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
        action='team_member_removed_by_captain',
        payload={'member_user_id': str(member_user_id)},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(None)

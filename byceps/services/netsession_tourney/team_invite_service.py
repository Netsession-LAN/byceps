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

from .coin_service import (
    charge_coins_for_tournament_registration,
)
from .dbmodels import (
    DbNetsessionTourneyParticipant,
)
from .models import (
    CoinChargeMode,
    Participant,
    ParticipantID,
    ParticipantType,
    RegistrationMode,
    TeamMemberRole,
    TournamentID,
    TournamentStatus,
)
from .registration_service import (
    ensure_registration_is_registered,
    generate_unique_invite_code_for_tournament,
)
from .registration_validation import (
    get_max_team_member_count,
)
from .service_helpers import (
    append_audit_log,
    db_participant_to_model,
    db_tournament_to_model,
)
from .team_captain_service import (
    count_team_members,
    find_db_managed_team_participant,
)
from .team_parts_membership import add_team_member
from .tournament_queries import (
    ACTIVE_PARTICIPANT_STATUS_VALUES,
    find_db_tournament_for_party,
)
from .tourney_registration_checks import validate_user_can_enter_tournament


def join_team_by_invite_code(
    party_id: PartyID,
    tournament_id: TournamentID,
    invite_code: str,
    user: User,
) -> Result[Participant, str]:
    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament = db_tournament_to_model(db_tournament)
    if tournament.registration_mode == RegistrationMode.solo:
        return Err('Dieses Turnier erlaubt nur Solo-Anmeldungen.')

    entry_error = validate_user_can_enter_tournament(
        party_id, tournament_id, tournament, user.id, check_capacity=False
    )
    if entry_error is not None:
        return Err(entry_error)

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
    max_team_member_count = get_max_team_member_count(tournament)
    if max_team_member_count is not None:
        member_count = count_team_members(db_participant.id)
        if int(member_count or 0) >= max_team_member_count:
            return Err('Dieses Team ist bereits voll.')

    if tournament.coin_charge_mode == CoinChargeMode.all_members:
        charge_result = charge_coins_for_tournament_registration(
            party_id,
            tournament,
            user.id,
            created_by_user_id=user.id,
        )
        if charge_result.is_err():
            return Err(charge_result.unwrap_err())

    ensure_registration_is_registered(tournament_id, user.id)
    add_team_member(
        db_participant.id, user.id, TeamMemberRole.player, datetime.utcnow()
    )
    db.session.commit()

    return Ok(db_participant_to_model(db_participant))


def get_team_invite_code_for_manager(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    manager_user_id: UserID,
) -> Result[str, str]:
    db_participant = find_db_managed_team_participant(
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

    invite_code = generate_unique_invite_code_for_tournament(tournament_id)
    db_participant.invite_code = invite_code

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='participant',
        object_id=participant_id,
        action='team_invite_code_regenerated',
        payload={},
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    return Ok(invite_code)

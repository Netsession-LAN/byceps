"""
byceps.services.netsession_tourney.team_admin_checks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Checks for team changes by an admin.
"""

from __future__ import annotations

from byceps.services.party.models import PartyID
from byceps.services.user.models import UserID
from byceps.util.result import Err, Ok, Result

from .eligibility import (
    validate_user_uses_ticket_for_party as _validate_user_uses_ticket_for_party,
)
from .models import (
    ParticipantID,
    RegistrationMode,
    Tournament,
    TournamentID,
    TournamentStatus,
)
from .participant_state import (
    count_active_participants_for_tournament,
    is_user_already_active_participant,
)
from .registration_validation import (
    get_max_team_member_count,
)
from .team_captain_service import (
    count_team_members,
)


def _check_team_admin_tournament_state(tournament: Tournament) -> str | None:
    if tournament.status != TournamentStatus.draft:
        return 'Teilnehmer lassen sich nur im Entwurf verwalten.'
    if tournament.registration_mode == RegistrationMode.solo:
        return 'Bei Einzelanmeldung gibt es keine Teamverwaltung.'
    return None


def _check_user_registrable_by_admin(
    party_id: PartyID, tournament_id: TournamentID, user_id: UserID
) -> Result[None, str]:
    if (
        ticket_check := _validate_user_uses_ticket_for_party(user_id, party_id)
    ).is_err():
        return ticket_check
    if is_user_already_active_participant(tournament_id, user_id):
        return Err('Du bist in diesem Turnier bereits aktiv angemeldet.')
    return Ok(None)


def _check_team_registration_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    tournament: Tournament,
    captain_user_id: UserID,
) -> Result[None, str]:
    user_check = _check_user_registrable_by_admin(
        party_id, tournament_id, captain_user_id
    )
    if user_check.is_err():
        return user_check

    if tournament.participant_limit is not None:
        active_count = count_active_participants_for_tournament(
            party_id, tournament_id
        )
        if active_count >= tournament.participant_limit:
            return Err('Das Turnier ist voll.')

    return Ok(None)


def _check_team_member_addable_by_admin(
    party_id: PartyID,
    tournament_id: TournamentID,
    tournament: Tournament,
    participant_id: ParticipantID,
    member_user_id: UserID,
) -> Result[None, str]:
    user_check = _check_user_registrable_by_admin(
        party_id, tournament_id, member_user_id
    )
    if user_check.is_err():
        return user_check

    max_team_member_count = get_max_team_member_count(tournament)
    if max_team_member_count is not None:
        member_count = count_team_members(participant_id)
        if int(member_count or 0) >= max_team_member_count:
            return Err('Dieses Team ist bereits voll.')

    return Ok(None)

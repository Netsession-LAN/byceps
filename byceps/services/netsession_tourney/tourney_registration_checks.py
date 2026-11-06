"""
byceps.services.netsession_tourney.tourney_registration_checks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Checks shared by the ways a user enters a tournament: registering solo,
creating a team, joining a team by invite code.
"""

from __future__ import annotations

from datetime import datetime

from byceps.services.party.models import PartyID
from byceps.services.user.models import UserID

from . import domain_service
from .eligibility import (
    validate_user_uses_ticket_for_party as _validate_user_uses_ticket_for_party,
)
from .models import Tournament, TournamentID
from .participant_state import (
    _is_tournament_full,
    _is_user_already_active_participant,
    count_active_participants_for_tournament,
)
from .registration_locks import (
    lock_tournament_for_registration,
    lock_user_coins,
)


def validate_user_can_enter_tournament(
    party_id: PartyID,
    tournament_id: TournamentID,
    tournament: Tournament,
    user_id: UserID,
    *,
    check_capacity: bool,
) -> str | None:
    """Return the first error message, or `None` if the user may enter.

    Checks, in this order: registration open, ticket, not already an
    active participant and (if requested) the tournament not being full.
    Locks the tournament and the user's coins first, so that simultaneous
    registrations are checked one after the other.
    """
    lock_tournament_for_registration(tournament_id)
    lock_user_coins(user_id)

    validation_result = domain_service.validate_registration_open(
        tournament, datetime.utcnow()
    )
    if validation_result.is_err():
        return validation_result.unwrap_err()

    ticket_validation_result = _validate_user_uses_ticket_for_party(
        user_id, party_id
    )
    if ticket_validation_result.is_err():
        return ticket_validation_result.unwrap_err()

    if _is_user_already_active_participant(tournament_id, user_id):
        return 'Du bist in diesem Turnier bereits aktiv angemeldet.'

    if not check_capacity:
        return None

    active_participant_count = count_active_participants_for_tournament(
        party_id, tournament_id
    )
    if _is_tournament_full(tournament, active_participant_count):
        return 'Das Turnier ist voll.'

    return None

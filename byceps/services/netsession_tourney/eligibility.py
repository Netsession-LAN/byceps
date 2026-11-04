"""
byceps.services.netsession_tourney.eligibility
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Who may take part in a party's tournaments.
"""

from __future__ import annotations

from byceps.services.party.models import PartyID
from byceps.services.ticketing import ticket_service
from byceps.services.user.models import UserID
from byceps.util.result import Err, Ok, Result


def validate_user_uses_ticket_for_party(
    user_id: UserID, party_id: PartyID
) -> Result[None, str]:
    """Players must use a ticket for the party – also when an admin adds
    them to a tournament or team."""
    if ticket_service.uses_any_ticket_for_party(user_id, party_id):
        return Ok(None)

    return Err(
        'Für die Turnieranmeldung brauchst du ein Ticket für diese Party, das dir zugewiesen ist.'
    )

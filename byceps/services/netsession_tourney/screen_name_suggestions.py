"""
byceps.services.netsession_tourney.screen_name_suggestions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Screen names of a party's ticket users, offered as suggestions in forms.
"""

from __future__ import annotations

from byceps.services.party.models import PartyID
from byceps.services.ticketing import ticket_service
from byceps.services.user import user_service


def get_suggested_screen_names_for_party(party_id: PartyID) -> list[str]:
    user_ids = ticket_service.get_ticket_users_for_party(party_id)
    users = user_service.get_users(user_ids)

    return sorted(
        {
            user.screen_name
            for user in users
            if user.screen_name and not getattr(user, 'deleted', False)
        },
        key=str.lower,
    )

"""
byceps.services.netsession_tourney.blueprints.admin.routes_create_review_data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Completeness check and selected admins of the review step of the
tournament creation wizard (see `routes_create_steps` and
`routes_create`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from byceps.services.netsession_tourney.blueprints.admin.wizard_helpers import (
    is_wizard_details_complete,
    is_wizard_format_complete,
    is_wizard_schedule_complete,
)
from byceps.services.party.models import PartyID
from byceps.services.user import user_service
from byceps.services.user.models import UserID
from byceps.util.views import redirect_to


def redirect_if_wizard_incomplete(party_id: PartyID, state: dict) -> Any:
    """Return a redirect to the first incomplete step, or `None`."""
    if not is_wizard_format_complete(state):
        return redirect_to('.create_wizard_format', party_id=party_id)
    if not is_wizard_details_complete(state):
        return redirect_to('.create_wizard_details', party_id=party_id)
    if not is_wizard_schedule_complete(state):
        return redirect_to('.create_wizard_schedule', party_id=party_id)
    return None


def _parse_selected_admin_ids(state: dict) -> set[UserID]:
    selected_admin_ids: set[UserID] = set()
    for raw_user_id in state.get('admin_user_ids', []):
        if not raw_user_id:
            continue

        try:
            selected_admin_ids.add(UserID(UUID(raw_user_id)))
        except ValueError:
            continue
    return selected_admin_ids


def get_selected_admin_users(state: dict) -> list[Any]:
    """Return the admins selected in the wizard, sorted by name."""
    return sorted(
        user_service.get_users(_parse_selected_admin_ids(state)),
        key=lambda user: user.screen_name.lower(),
    )

"""
byceps.services.netsession_tourney.blueprints.admin.routes_tournament_form_checks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Checks of the logo and Discord image fields shared by the tournament
form routes (see `routes_tournament_update`, `routes_create_details`
and `routes_participants_matches`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.logo_service import (
    is_known_discord_forum_image_url,
    is_known_sponsor_logo_url,
    is_known_tournament_logo_url,
)
from byceps.services.party.models import PartyID


def stripped_or_none(value: str | None) -> str | None:
    """Return the stripped value, or `None` if it is empty."""
    return value.strip() if value else None


def is_invalid_tournament_logo_url(
    party_id: PartyID, tournament_logo_url: str | None
) -> bool:
    """Return true if a tournament logo was selected that is unknown."""
    return bool(
        tournament_logo_url
        and not is_known_tournament_logo_url(party_id, tournament_logo_url)
    )


def get_sponsor_logo_error(
    party_id: PartyID, is_sponsored: bool, sponsor_logo_url: str | None
) -> str | None:
    """Return the error message for the sponsor logo, if any."""
    if is_sponsored and not sponsor_logo_url:
        return gettext('Bitte ein Sponsor-Logo auswählen.')
    if sponsor_logo_url and not is_known_sponsor_logo_url(
        party_id, sponsor_logo_url
    ):
        return gettext('Ungültiges Sponsor-Logo ausgewählt.')
    return None


def is_invalid_discord_forum_image_url(
    party_id: PartyID, discord_forum_image_url: str | None
) -> bool:
    """Return true if a Discord forum image was selected that is unknown."""
    return bool(
        discord_forum_image_url
        and not is_known_discord_forum_image_url(
            party_id, discord_forum_image_url
        )
    )

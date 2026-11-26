"""
byceps.services.netsession_tourney.blueprints.admin.routes_overview_coin_settings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Steps of the coin settings routes: settings form, ticket category
amounts and storing the settings (see `routes_overview_coins`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import Any

from flask import g, request
from flask_babel import gettext

from byceps.services.netsession_tourney import coin_service
from byceps.services.netsession_tourney.forms import CoinSettingsForm
from byceps.services.party.models import PartyID
from byceps.services.ticketing import ticket_category_service
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.result import Err, Ok, Result


def get_category_amounts_by_id(party_id: PartyID) -> dict[Any, Any]:
    """Return the coin amount per ticket category."""
    return {
        item.ticket_category_id: item.coin_amount
        for item in coin_service.get_ticket_category_coin_settings_for_party(
            party_id
        )
    }


def build_settings_form(
    erroneous_settings_form: Any, settings: Any
) -> CoinSettingsForm:
    """Return the erroneous form or one filled with the settings."""
    return (
        erroneous_settings_form
        if erroneous_settings_form is not None
        else CoinSettingsForm(
            data={
                'enabled': settings.enabled,
                'default_coin_amount': settings.default_coin_amount,
            }
        )
    )


def _parse_category_coin_amount(category: Any) -> Result[int | None, str]:
    raw_value = (request.form.get(f'category_coin_{category.id}') or '').strip()
    if not raw_value:
        return Ok(None)

    try:
        amount = int(raw_value)
    except ValueError:
        return Err(
            gettext(
                'Für die Ticket-Kategorie "%(title)s" ist kein gültiger Coin-Wert eingetragen.',
                title=category.title,
            )
        )

    if amount < 0:
        return Err(
            gettext(
                'Für die Ticket-Kategorie "%(title)s" muss der Coin-Wert 0 oder größer sein.',
                title=category.title,
            )
        )

    return Ok(amount)


def parse_category_coin_amounts(party_id: PartyID) -> dict[Any, int] | None:
    """Return the submitted amount per category; flash an error."""
    category_coin_amounts = {}
    for category in ticket_category_service.get_categories_for_party(party_id):
        parsed_amount = _parse_category_coin_amount(category)
        if parsed_amount.is_err():
            flash_error(parsed_amount.unwrap_err())
            return None

        amount = parsed_amount.unwrap()
        if amount is not None:
            category_coin_amounts[category.id] = amount
    return category_coin_amounts


def configure_coin_settings(
    party_id: PartyID,
    form: CoinSettingsForm,
    category_coin_amounts: dict[Any, int],
) -> bool:
    """Store the coin settings; flash the outcome; return success."""
    match coin_service.configure_coin_settings(
        party_id,
        g.user.as_user(),
        enabled=bool(form.enabled.data),
        default_coin_amount=form.default_coin_amount.data,
        ticket_category_coin_amounts=category_coin_amounts,
    ):
        case Ok(_settings):
            flash_success(gettext('Coin-Einstellungen wurden gespeichert.'))
        case Err(message):
            flash_error(gettext(message))
            return False

    return True

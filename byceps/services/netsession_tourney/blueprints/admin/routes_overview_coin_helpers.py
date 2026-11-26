"""
byceps.services.netsession_tourney.blueprints.admin.routes_overview_coin_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Steps of the coin routes: searched user and manual adjustments (see
`routes_overview_coins`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import Any

from flask import g, request
from flask_babel import gettext

from byceps.services.netsession_tourney import coin_service
from byceps.services.netsession_tourney.forms import (
    CoinAdjustmentForm,
)
from byceps.services.party.models import PartyID
from byceps.services.user import user_service
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.result import Err, Ok


def get_searched_screen_name(erroneous_adjustment_form: Any) -> str:
    """Return the searched screen name of the request or the form."""
    searched_screen_name = (request.args.get('screen_name') or '').strip()
    if (
        not searched_screen_name
        and erroneous_adjustment_form is not None
        and erroneous_adjustment_form.screen_name.data
    ):
        searched_screen_name = (
            erroneous_adjustment_form.screen_name.data.strip()
        )
    return searched_screen_name


def get_selected_user_data(
    party_id: PartyID, searched_screen_name: str
) -> tuple[Any, Any, list[Any]]:
    """Return user, coin balance and recent coin entries."""
    selected_user = (
        user_service.find_user_by_screen_name(searched_screen_name)
        if searched_screen_name
        else None
    )
    selected_user_balance = (
        coin_service.get_user_coin_balance(party_id, selected_user.id)
        if selected_user is not None
        else None
    )
    recent_coin_entries = (
        coin_service.get_recent_coin_ledger_entries_for_user(
            party_id, selected_user.id
        )
        if selected_user is not None
        else []
    )
    return selected_user, selected_user_balance, recent_coin_entries


def build_adjustment_form(
    erroneous_adjustment_form: Any, searched_screen_name: str
) -> CoinAdjustmentForm:
    """Return the erroneous form or one with the searched screen name."""
    return (
        erroneous_adjustment_form
        if erroneous_adjustment_form is not None
        else CoinAdjustmentForm(
            data={'screen_name': searched_screen_name}
            if searched_screen_name
            else None
        )
    )


def _get_amount_error(plus_amount: Any, minus_amount: Any) -> str | None:
    if plus_amount and minus_amount:
        return gettext(
            'Bitte nur Plus-Coins oder Minus-Coins eintragen, nicht beides gleichzeitig.'
        )
    if not plus_amount and not minus_amount:
        return gettext(
            'Bitte einen Wert bei Plus-Coins oder Minus-Coins eintragen.'
        )
    return None


def parse_amount_delta(form: CoinAdjustmentForm) -> Any:
    """Return the signed amount of the adjustment, or `None`; flash an error."""
    plus_amount = form.plus_amount.data or 0
    minus_amount = form.minus_amount.data or 0
    amount_error = _get_amount_error(plus_amount, minus_amount)
    if amount_error is not None:
        flash_error(amount_error)
        return None

    return plus_amount if plus_amount else -minus_amount


def adjust_user_coins(
    party_id: PartyID, user: Any, amount_delta: Any, form: CoinAdjustmentForm
) -> bool:
    """Adjust the coins of the user; flash the outcome; return success."""
    match coin_service.adjust_user_coins(
        party_id,
        user.id,
        amount_delta,
        form.note.data or '',
        g.user.as_user(),
    ):
        case Ok(_balance):
            flash_success(
                gettext(
                    'Die Coins für "%(screen_name)s" wurden angepasst.',
                    screen_name=user.screen_name,
                )
            )
        case Err(message):
            flash_error(gettext(message))
            return False

    return True

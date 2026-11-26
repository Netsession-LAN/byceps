"""
byceps.services.netsession_tourney.blueprints.admin.routes_overview_coins
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Routes to show and change the coin settings of a party and to adjust
the coins of a user (see `routes_overview`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import Any

from flask import request
from flask_babel import gettext

from byceps.services.netsession_tourney import coin_service
from byceps.services.netsession_tourney.blueprints.admin.result_helpers import (
    get_party_or_404,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_overview_coin_helpers import (
    adjust_user_coins,
    build_adjustment_form,
    get_searched_screen_name,
    get_selected_user_data,
    parse_amount_delta,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_overview_coin_settings import (
    build_settings_form,
    configure_coin_settings,
    get_category_amounts_by_id,
    parse_category_coin_amounts,
)
from byceps.services.netsession_tourney.forms import (
    CoinAdjustmentForm,
    CoinSettingsForm,
)
from byceps.services.netsession_tourney.screen_name_suggestions import (
    get_suggested_screen_names_for_party,
)
from byceps.services.ticketing import ticket_category_service
from byceps.services.user import user_service
from byceps.util.framework.flash import flash_error
from byceps.util.framework.templating import templated
from byceps.util.views import permission_required, redirect_to


def _build_coins_index_context(
    party: Any, erroneous_settings_form: Any, erroneous_adjustment_form: Any
) -> dict[str, Any]:
    settings = coin_service.get_coin_settings(party.id)
    categories = ticket_category_service.get_categories_for_party(party.id)
    category_amounts_by_id = get_category_amounts_by_id(party.id)
    settings_form = build_settings_form(erroneous_settings_form, settings)
    searched_screen_name = get_searched_screen_name(erroneous_adjustment_form)
    selected_user, selected_user_balance, recent_coin_entries = (
        get_selected_user_data(party.id, searched_screen_name)
    )
    adjustment_form = build_adjustment_form(
        erroneous_adjustment_form, searched_screen_name
    )

    return {
        'party': party,
        'settings': settings,
        'settings_form': settings_form,
        'ticket_categories': categories,
        'category_amounts_by_id': category_amounts_by_id,
        'adjustment_form': adjustment_form,
        'searched_screen_name': searched_screen_name,
        'selected_user': selected_user,
        'selected_user_balance': selected_user_balance,
        'recent_coin_entries': recent_coin_entries,
        'suggested_screen_names': get_suggested_screen_names_for_party(
            party.id
        ),
    }


def register_coin_routes(blueprint) -> None:
    @blueprint.get('/for_party/<party_id>/coins')
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/coins/index')
    def coins_index(
        party_id, erroneous_settings_form=None, erroneous_adjustment_form=None
    ):
        party = get_party_or_404(party_id)
        return _build_coins_index_context(
            party, erroneous_settings_form, erroneous_adjustment_form
        )

    @blueprint.post('/for_party/<party_id>/coins')
    @permission_required('netsession_tourney.manage')
    def coins_update(party_id):
        party = get_party_or_404(party_id)
        form = CoinSettingsForm(request.form)
        if not form.validate():
            flash_error(
                gettext('Coin-Einstellungen konnten nicht gespeichert werden.')
            )
            return coins_index(party.id, erroneous_settings_form=form)

        category_coin_amounts = parse_category_coin_amounts(party.id)
        if category_coin_amounts is None:
            return coins_index(party.id, erroneous_settings_form=form)

        if not configure_coin_settings(party.id, form, category_coin_amounts):
            return coins_index(party.id, erroneous_settings_form=form)

        return redirect_to('.coins_index', party_id=party.id)

    @blueprint.post('/for_party/<party_id>/coins/adjust')
    @permission_required('netsession_tourney.manage')
    def coins_adjust(party_id):
        party = get_party_or_404(party_id)
        form = CoinAdjustmentForm(request.form)
        if not form.validate():
            flash_error(
                gettext('Coin-Anpassung konnte nicht gespeichert werden.')
            )
            return coins_index(
                party.id,
                erroneous_adjustment_form=form,
            )

        user = user_service.find_user_by_screen_name(
            form.screen_name.data.strip()
        )
        if user is None:
            flash_error(gettext('Der angegebene User wurde nicht gefunden.'))
            return coins_index(
                party.id,
                erroneous_adjustment_form=form,
            )

        amount_delta = parse_amount_delta(form)
        if amount_delta is None or not adjust_user_coins(
            party.id, user, amount_delta, form
        ):
            return coins_index(
                party.id,
                erroneous_adjustment_form=form,
            )

        return redirect_to(
            '.coins_index',
            party_id=party.id,
            screen_name=user.screen_name,
        )

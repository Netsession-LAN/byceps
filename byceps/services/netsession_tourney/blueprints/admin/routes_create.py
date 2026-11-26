"""
byceps.services.netsession_tourney.blueprints.admin.routes_create
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.blueprints.admin.result_helpers import (
    get_party_or_404,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_create_details import (
    register_create_details_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_create_review_data import (
    redirect_if_wizard_incomplete,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_create_steps import (
    register_create_review_routes,
    register_create_schedule_routes,
    register_create_start_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_create_tournament import (
    create_tournament_from_state,
    finish_tournament_creation,
)
from byceps.services.netsession_tourney.blueprints.admin.wizard_helpers import (
    assert_party_has_categories_or_redirect,
    get_create_wizard_state,
    parse_category_id,
)
from byceps.util.framework.flash import flash_error
from byceps.util.views import permission_required, redirect_to


def register(blueprint):
    register_create_start_routes(blueprint)
    register_create_details_routes(blueprint)
    register_create_schedule_routes(blueprint)
    register_create_review_routes(blueprint)

    @blueprint.post('/for_party/<party_id>/create/review')
    @permission_required('netsession_tourney.manage')
    def create_wizard_review_submit(party_id):
        party = get_party_or_404(party_id)
        redirect_response = assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = get_create_wizard_state(party.id)
        incomplete_redirect = redirect_if_wizard_incomplete(party.id, state)
        if incomplete_redirect is not None:
            return incomplete_redirect

        category_id = parse_category_id(state.get('category_id'))
        if category_id is None:
            flash_error(gettext('Bitte eine gültige Kategorie auswählen.'))
            return redirect_to('.create_wizard_format', party_id=party.id)

        return finish_tournament_creation(
            party.id,
            state,
            create_tournament_from_state(party.id, state, category_id),
        )

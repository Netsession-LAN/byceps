"""
byceps.services.netsession_tourney.blueprints.admin.routes_create_details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Routes of the details step of the tournament creation wizard (see
`routes_create`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import request

from byceps.services.netsession_tourney.blueprints.admin.result_helpers import (
    get_party_or_404,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_create_details_form import (
    build_details_state,
    parse_details_selection,
)
from byceps.services.netsession_tourney.blueprints.admin.wizard_forms import (
    build_wizard_details_form,
)
from byceps.services.netsession_tourney.blueprints.admin.wizard_helpers import (
    assert_party_has_categories_or_redirect,
    get_create_wizard_state,
    is_wizard_format_complete,
    set_create_wizard_state,
)
from byceps.services.netsession_tourney.forms import (
    TournamentWizardDetailsForm,
)
from byceps.util.framework.templating import templated
from byceps.util.views import permission_required, redirect_to


def register_create_details_routes(blueprint) -> None:
    @blueprint.get('/for_party/<party_id>/create/details')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/wizard/details')
    def create_wizard_details(party_id, erroneous_form=None):
        party = get_party_or_404(party_id)
        redirect_response = assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = get_create_wizard_state(party.id)
        if not is_wizard_format_complete(state):
            return redirect_to('.create_wizard_format', party_id=party.id)

        form = build_wizard_details_form(
            party.id,
            state=state,
            erroneous_form=erroneous_form,
        )

        return {
            'party': party,
            'form': form,
            'wizard_step': 'details',
        }

    @blueprint.post('/for_party/<party_id>/create/details')
    @permission_required('netsession_tourney.manage')
    def create_wizard_details_submit(party_id):
        party = get_party_or_404(party_id)
        redirect_response = assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = get_create_wizard_state(party.id)
        if not is_wizard_format_complete(state):
            return redirect_to('.create_wizard_format', party_id=party.id)

        form = build_wizard_details_form(
            party.id,
            state=state,
            erroneous_form=TournamentWizardDetailsForm(request.form),
        )
        if not form.validate():
            return create_wizard_details(party.id, form)

        selection = parse_details_selection(party.id, form)
        if selection is None:
            return create_wizard_details(party.id, form)

        state.update(build_details_state(form, selection))
        set_create_wizard_state(party.id, state)

        return redirect_to('.create_wizard_schedule', party_id=party.id)

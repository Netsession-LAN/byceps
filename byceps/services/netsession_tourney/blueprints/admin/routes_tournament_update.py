"""
byceps.services.netsession_tourney.blueprints.admin.routes_tournament_update
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Routes to show and submit the tournament update form (see
`routes_tournament`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.blueprints.admin.result_helpers import (
    _get_tournament_or_404,
    get_party_or_404,
)
from byceps.services.netsession_tourney.blueprints.admin.result_redirects import (
    redirect_to_related_tournament_view,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_tournament_update_helpers import (
    build_submitted_update_form,
    build_update_form_context,
    handle_update_result,
    parse_update_selection,
    update_tournament_from_form,
)
from byceps.services.netsession_tourney.blueprints.admin.wizard_helpers import (
    assert_party_has_categories_or_redirect,
)
from byceps.util.framework.templating import templated
from byceps.util.views import permission_required


def register_tournament_update_routes(blueprint) -> None:
    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/update'
    )
    @permission_required('netsession_tourney.manage')
    @templated
    def update_form(party_id, tournament_id, erroneous_form=None):
        party = get_party_or_404(party_id)
        redirect_response = assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        return build_update_form_context(party, tournament_id, erroneous_form)

    @blueprint.post('/for_party/<party_id>/tournaments/<uuid:tournament_id>')
    @permission_required('netsession_tourney.manage')
    def update(party_id, tournament_id):
        party = get_party_or_404(party_id)
        redirect_response = assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        tournament = _get_tournament_or_404(party.id, tournament_id)

        form, available_admin_user_ids = build_submitted_update_form(
            party.id, tournament
        )
        if not form.validate():
            return update_form(party.id, tournament.id, form)

        selection = parse_update_selection(party.id, form)
        if selection is None:
            return update_form(party.id, tournament.id, form)

        mode_changed = form.mode.data != tournament.mode.value
        registration_mode_changed = (
            form.registration_mode.data != tournament.registration_mode.value
        )

        result = update_tournament_from_form(
            party.id, tournament.id, form, selection
        )
        if not handle_update_result(
            result,
            party.id,
            tournament.id,
            form,
            available_admin_user_ids,
            mode_changed,
            registration_mode_changed,
        ):
            return update_form(party.id, tournament.id, form)

        return redirect_to_related_tournament_view(party.id, tournament.id)

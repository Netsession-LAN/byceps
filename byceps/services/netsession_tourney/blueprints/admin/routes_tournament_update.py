"""
byceps.services.netsession_tourney.blueprints.admin.routes_tournament_update
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Routes to show and submit the tournament update form (see
`routes_tournament`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import Any

from byceps.services.netsession_tourney import (
    tournament_admin_service,
    tournament_queries,
)
from byceps.services.netsession_tourney.blueprints.admin.result_helpers import (
    _get_tournament_or_404,
    get_party_or_404,
)
from byceps.services.netsession_tourney.blueprints.admin.result_redirects import (
    redirect_to_related_tournament_view,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_tournament_update_helpers import (
    build_submitted_update_form,
    handle_update_result,
    parse_update_selection,
    set_update_form_choices,
    update_tournament_from_form,
)
from byceps.services.netsession_tourney.blueprints.admin.wizard_helpers import (
    assert_party_has_categories_or_redirect,
    get_available_tournament_admin_users,
    update_form_with_categories,
)
from byceps.services.netsession_tourney.forms import TournamentForm
from byceps.util.framework.templating import templated
from byceps.util.views import permission_required


def build_update_form_data(
    tournament: Any, assigned_admin_user_ids: Any
) -> dict[str, Any]:
    """Return the form data to show the stored tournament."""
    return {
        'slug': tournament.slug,
        'title': tournament.title,
        'subtitle': tournament.subtitle,
        'tournament_logo_url': tournament.logo_url,
        'is_sponsored': tournament.is_sponsored,
        'sponsor_logo_url': tournament.sponsor_logo_url,
        'game': tournament.game,
        'category_id': str(tournament.category_id),
        'mode': tournament.mode.value,
        'registration_mode': tournament.registration_mode.value,
        'starts_at': tournament.starts_at,
        'visible_on_site': tournament.visible_on_site,
        'rules_template_slug': tournament.rules_page_slug,
        'registration_open': tournament.registration_open,
        'registration_deadline': tournament.registration_deadline,
        'roster_lock_at': tournament.roster_lock_at,
        'checkin_open_at': tournament.checkin_open_at,
        'checkin_close_at': tournament.checkin_close_at,
        'team_size': tournament.team_size or 1,
        'substitute_count': tournament.substitute_count or 0,
        'participant_limit': tournament.participant_limit,
        'coin_cost': tournament.coin_cost,
        'coin_refund_policy': tournament.coin_refund_policy.value,
        'coin_charge_mode': tournament.coin_charge_mode.value,
        'admin_user_ids': [
            str(user_id) for user_id in sorted(assigned_admin_user_ids, key=str)
        ],
    }


def build_update_form_context(
    party: Any, tournament_id: Any, erroneous_form: Any
) -> dict[str, Any]:
    """Return the template context of the tournament update form."""
    tournament = _get_tournament_or_404(party.id, tournament_id)
    available_admin_users = get_available_tournament_admin_users()
    assigned_admin_user_ids = (
        tournament_admin_service.get_tournament_admin_user_ids(tournament.id)
    )

    if erroneous_form:
        form = update_form_with_categories(
            party.id,
            category_id=tournament.category_id,
            erroneous_form=erroneous_form,
        )
    else:
        data = build_update_form_data(tournament, assigned_admin_user_ids)
        form = update_form_with_categories(
            party.id,
            category_id=tournament.category_id,
            erroneous_form=TournamentForm(data=data),
        )
        form.registration_mode.data = tournament.registration_mode.value
        form.mode.data = tournament.mode.value
        form.category_id.data = str(tournament.category_id)
    set_update_form_choices(form, party.id, tournament, available_admin_users)

    return {
        'party': party,
        'tournament': tournament,
        'stages': tournament_queries.get_stages_for_tournament(
            party.id, tournament.id
        ),
        'form': form,
    }


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

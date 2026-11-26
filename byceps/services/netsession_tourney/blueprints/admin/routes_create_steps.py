"""
byceps.services.netsession_tourney.blueprints.admin.routes_create_steps
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Routes of the tournament creation wizard: start, format,
schedule and review steps (see `routes_create`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from uuid import UUID

from flask import request

from byceps.services.netsession_tourney.forms import (
    TournamentWizardFormatForm,
    TournamentWizardScheduleForm,
)
from byceps.services.netsession_tourney.models import (
    CoinChargeMode,
    RegistrationMode,
)
from byceps.services.netsession_tourney.tournament_category_service import (
    get_tournament_categories_for_party,
)
from byceps.services.netsession_tourney.tournament_rule_template_service import (
    get_tournament_rule_templates_for_party,
)
from byceps.services.user import user_service
from byceps.services.user.models import UserID
from byceps.util.framework.templating import templated
from byceps.util.views import permission_required, redirect_to

from .result_helpers import get_party_or_404
from .wizard_forms import (
    build_wizard_format_form,
    build_wizard_schedule_form,
)
from .wizard_helpers import (
    assert_party_has_categories_or_redirect,
    get_create_wizard_state,
    is_wizard_details_complete,
    is_wizard_format_complete,
    is_wizard_schedule_complete,
    parse_admin_user_ids,
    serialize_datetime_local,
    set_create_wizard_state,
)


def register_create_start_routes(blueprint):
    @blueprint.get('/for_party/<party_id>/create')
    @permission_required('netsession_tourney.manage')
    def create_form(party_id):
        return redirect_to('.create_wizard_format', party_id=party_id)

    @blueprint.post('/for_party/<party_id>')
    @permission_required('netsession_tourney.manage')
    def create(party_id):
        return redirect_to('.create_wizard_format', party_id=party_id)

    @blueprint.get('/for_party/<party_id>/create/format')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/wizard/format')
    def create_wizard_format(party_id, erroneous_form=None):
        party = get_party_or_404(party_id)
        redirect_response = assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = get_create_wizard_state(party.id)
        form, _ = build_wizard_format_form(
            party.id,
            state=state,
            erroneous_form=erroneous_form,
        )

        return {
            'party': party,
            'form': form,
            'wizard_step': 'format',
        }

    @blueprint.post('/for_party/<party_id>/create/format')
    @permission_required('netsession_tourney.manage')
    def create_wizard_format_submit(party_id):
        party = get_party_or_404(party_id)
        redirect_response = assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = get_create_wizard_state(party.id)
        form, available_admin_user_ids = build_wizard_format_form(
            party.id,
            state=state,
            erroneous_form=TournamentWizardFormatForm(request.form),
        )
        if not form.validate():
            return create_wizard_format(party.id, form)

        selected_admin_user_ids = parse_admin_user_ids(
            form.admin_user_ids.data, available_admin_user_ids
        )
        registration_mode = RegistrationMode(form.registration_mode.data)

        state.update(
            {
                'category_id': form.category_id.data,
                'mode': form.mode.data,
                'registration_mode': form.registration_mode.data,
                'team_size': 1
                if registration_mode == RegistrationMode.solo
                else form.team_size.data,
                'substitute_count': 0
                if registration_mode == RegistrationMode.solo
                else form.substitute_count.data,
                'participant_limit': form.participant_limit.data,
                'coin_cost': form.coin_cost.data,
                'coin_refund_policy': form.coin_refund_policy.data,
                'coin_charge_mode': CoinChargeMode.all_members.value
                if registration_mode == RegistrationMode.solo
                else form.coin_charge_mode.data,
                'admin_user_ids': [
                    str(user_id) for user_id in selected_admin_user_ids
                ],
            }
        )
        set_create_wizard_state(party.id, state)

        return redirect_to('.create_wizard_details', party_id=party.id)


def register_create_schedule_routes(blueprint):
    @blueprint.get('/for_party/<party_id>/create/schedule')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/wizard/schedule')
    def create_wizard_schedule(party_id, erroneous_form=None):
        party = get_party_or_404(party_id)
        redirect_response = assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = get_create_wizard_state(party.id)
        if not is_wizard_format_complete(state):
            return redirect_to('.create_wizard_format', party_id=party.id)
        if not is_wizard_details_complete(state):
            return redirect_to('.create_wizard_details', party_id=party.id)

        form = build_wizard_schedule_form(
            party=party,
            state=state,
            erroneous_form=erroneous_form,
        )

        return {
            'party': party,
            'form': form,
            'wizard_step': 'schedule',
        }

    @blueprint.post('/for_party/<party_id>/create/schedule')
    @permission_required('netsession_tourney.manage')
    def create_wizard_schedule_submit(party_id):
        party = get_party_or_404(party_id)
        redirect_response = assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = get_create_wizard_state(party.id)
        if not is_wizard_format_complete(state):
            return redirect_to('.create_wizard_format', party_id=party.id)
        if not is_wizard_details_complete(state):
            return redirect_to('.create_wizard_details', party_id=party.id)

        form = TournamentWizardScheduleForm(request.form)
        if not form.validate():
            return create_wizard_schedule(party.id, form)

        state.update(
            {
                'starts_at': serialize_datetime_local(form.starts_at.data),
                'visible_on_site': bool(form.visible_on_site.data),
                'registration_open': bool(form.registration_open.data),
                'registration_deadline': serialize_datetime_local(
                    form.registration_deadline.data
                ),
                'roster_lock_at': serialize_datetime_local(
                    form.roster_lock_at.data
                ),
                'checkin_open_at': serialize_datetime_local(
                    form.checkin_open_at.data
                ),
                'checkin_close_at': serialize_datetime_local(
                    form.checkin_close_at.data
                ),
            }
        )
        set_create_wizard_state(party.id, state)

        return redirect_to('.create_wizard_review', party_id=party.id)


def register_create_review_routes(blueprint):
    @blueprint.get('/for_party/<party_id>/create/review')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/wizard/review')
    def create_wizard_review(party_id):
        party = get_party_or_404(party_id)
        redirect_response = assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = get_create_wizard_state(party.id)
        if not is_wizard_format_complete(state):
            return redirect_to('.create_wizard_format', party_id=party.id)
        if not is_wizard_details_complete(state):
            return redirect_to('.create_wizard_details', party_id=party.id)
        if not is_wizard_schedule_complete(state):
            return redirect_to('.create_wizard_schedule', party_id=party.id)

        categories_by_id = {
            str(category.id): category
            for category in get_tournament_categories_for_party(party.id)
        }
        selected_admin_ids: set[UserID] = set()
        for raw_user_id in state.get('admin_user_ids', []):
            if not raw_user_id:
                continue

            try:
                selected_admin_ids.add(UserID(UUID(raw_user_id)))
            except ValueError:
                continue
        selected_admin_users = sorted(
            user_service.get_users(selected_admin_ids),
            key=lambda user: user.screen_name.lower(),
        )
        rule_templates_by_slug = {
            template.slug: template
            for template in get_tournament_rule_templates_for_party(party.id)
        }
        selected_rules_template = rule_templates_by_slug.get(
            state.get('rules_page_slug')
        )

        return {
            'party': party,
            'state': state,
            'selected_category': categories_by_id.get(state.get('category_id')),
            'selected_admin_users': selected_admin_users,
            'selected_rules_template': selected_rules_template,
            'wizard_step': 'review',
        }

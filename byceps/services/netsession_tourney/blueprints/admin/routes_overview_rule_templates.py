"""
byceps.services.netsession_tourney.blueprints.admin.routes_overview_rule_templates
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Routes of the rule templates (see `routes_overview`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import request
from flask_babel import gettext

from byceps.services.netsession_tourney import (
    tournament_rule_template_service,
)
from byceps.services.netsession_tourney.forms import (
    TournamentRuleTemplateForm,
)
from byceps.services.netsession_tourney.models import RuleTemplateBodyFormat
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.views import (
    permission_required,
    redirect_to,
)

from .result_helpers import get_party_or_404
from .wizard_lookups import (
    get_tournament_rule_template_or_404,
)


def register_rule_template_create_routes(blueprint):
    @blueprint.get('/for_party/<party_id>/rules')
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/rule_template/index')
    def rule_template_index(party_id):
        party = get_party_or_404(party_id)
        rule_templates = tournament_rule_template_service.get_tournament_rule_templates_for_party(
            party.id
        )
        return {
            'party': party,
            'rule_templates': rule_templates,
        }

    @blueprint.get('/for_party/<party_id>/rules/create')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/rule_template/create_form')
    def rule_template_create_form(party_id, erroneous_form=None):
        party = get_party_or_404(party_id)
        form = (
            erroneous_form
            if erroneous_form is not None
            else TournamentRuleTemplateForm()
        )
        return {
            'party': party,
            'form': form,
        }

    @blueprint.post('/for_party/<party_id>/rules')
    @permission_required('netsession_tourney.manage')
    def rule_template_create(party_id):
        party = get_party_or_404(party_id)
        form = TournamentRuleTemplateForm(request.form)
        if not form.validate():
            return rule_template_create_form(party.id, form)

        match tournament_rule_template_service.create_tournament_rule_template(
            party.id,
            form.slug.data,
            form.title.data,
            RuleTemplateBodyFormat(form.body_format.data),
            form.body.data,
        ):
            case Ok(rule_template):
                flash_success(
                    gettext(
                        'Regeltemplate "%(title)s" wurde erstellt.',
                        title=rule_template.title,
                    )
                )
            case Err(message):
                flash_error(message)
                return rule_template_create_form(party.id, form)

        return redirect_to('.rule_template_index', party_id=party.id)


def register_rule_template_update_routes(blueprint):
    @blueprint.get('/rules/<uuid:rule_template_id>/update')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/rule_template/update_form')
    def rule_template_update_form(rule_template_id, erroneous_form=None):
        rule_template = get_tournament_rule_template_or_404(rule_template_id)
        party = get_party_or_404(rule_template.party_id)
        form = (
            erroneous_form
            if erroneous_form is not None
            else TournamentRuleTemplateForm(
                data={
                    'slug': rule_template.slug,
                    'title': rule_template.title,
                    'body_format': rule_template.body_format.value,
                    'body': rule_template.body,
                }
            )
        )
        return {
            'party': party,
            'rule_template': rule_template,
            'form': form,
        }

    @blueprint.post('/rules/<uuid:rule_template_id>')
    @permission_required('netsession_tourney.manage')
    def rule_template_update(rule_template_id):
        rule_template = get_tournament_rule_template_or_404(rule_template_id)
        party = get_party_or_404(rule_template.party_id)

        form = TournamentRuleTemplateForm(request.form)
        if not form.validate():
            return rule_template_update_form(rule_template.id, form)

        match tournament_rule_template_service.update_tournament_rule_template(
            rule_template.id,
            form.slug.data,
            form.title.data,
            RuleTemplateBodyFormat(form.body_format.data),
            form.body.data,
        ):
            case Ok(updated_rule_template):
                flash_success(
                    gettext(
                        'Regeltemplate "%(title)s" wurde aktualisiert.',
                        title=updated_rule_template.title,
                    )
                )
            case Err(message):
                flash_error(message)
                return rule_template_update_form(rule_template.id, form)

        return redirect_to('.rule_template_index', party_id=party.id)

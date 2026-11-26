"""
byceps.services.netsession_tourney.blueprints.admin.routes_overview_index
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Routes of the party overview, timetable, notification test and
tournament categories (see `routes_overview`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import g, request
from flask_babel import gettext

from byceps.services.netsession_tourney import (
    discord_dm_outbox,
    participant_admin_service,
    tournament_category_service,
    tournament_service,
)
from byceps.services.netsession_tourney.blueprints.site.timetable_helpers import (
    build_party_timetable,
)
from byceps.services.netsession_tourney.forms import (
    TournamentCategoryForm,
)
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.views import (
    permission_required,
    redirect_to,
    respond_no_content,
)

from .result_helpers import get_party_or_404
from .wizard_lookups import (
    get_tournament_category_or_404,
)


def register_overview_routes(blueprint):
    @blueprint.get('/for_party/<party_id>')
    @permission_required('netsession_tourney.view')
    @templated
    def index(party_id):
        party = get_party_or_404(party_id)
        tournaments = tournament_service.get_tournaments_for_party(party.id)
        categories = (
            tournament_category_service.get_tournament_categories_for_party(
                party.id
            )
        )
        categories_by_id = {category.id: category for category in categories}
        active_participant_counts_by_tournament_id = participant_admin_service.get_active_participant_counts_for_tournaments(
            party.id,
            {tournament.id for tournament in tournaments},
        )
        return {
            'party': party,
            'tournaments': tournaments,
            'categories_by_id': categories_by_id,
            'active_participant_counts_by_tournament_id': (
                active_participant_counts_by_tournament_id
            ),
        }

    @blueprint.get('/for_party/<party_id>/categories')
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/category/index')
    def category_index(party_id):
        party = get_party_or_404(party_id)
        categories = (
            tournament_category_service.get_tournament_categories_for_party(
                party.id
            )
        )
        return {
            'party': party,
            'categories': categories,
        }

    @blueprint.get('/for_party/<party_id>/timetable')
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/timetable')
    def timetable(party_id):
        party = get_party_or_404(party_id)
        selected_day_iso = (request.args.get('day') or '').strip() or None
        return {
            'party': party,
            'timetable': build_party_timetable(
                party, selected_day_iso=selected_day_iso
            ),
        }


def register_notification_test_routes(blueprint):
    @blueprint.post('/for_party/<party_id>/notifications/discord-dm/test')
    @permission_required('netsession_tourney.manage')
    def notifications_discord_dm_send_test(party_id):
        party = get_party_or_404(party_id)

        match discord_dm_outbox.send_test_discord_dm(party.id, g.user.id):
            case Err(message):
                flash_error(gettext(message))
            case Ok(_):
                flash_success(gettext('Discord-Testnachricht wurde gesendet.'))

        return redirect_to('.notifications_index', party_id=party.id)


def register_category_create_routes(blueprint):
    @blueprint.get('/for_party/<party_id>/categories/create')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/category/create_form')
    def category_create_form(party_id, erroneous_form=None):
        party = get_party_or_404(party_id)
        form = erroneous_form if erroneous_form else TournamentCategoryForm()
        return {
            'party': party,
            'form': form,
        }

    @blueprint.post('/for_party/<party_id>/categories')
    @permission_required('netsession_tourney.manage')
    def category_create(party_id):
        party = get_party_or_404(party_id)
        form = TournamentCategoryForm(request.form)
        if not form.validate():
            return category_create_form(party.id, form)

        match tournament_category_service.create_tournament_category(
            party.id, form.title.data
        ):
            case Ok(category):
                flash_success(
                    gettext(
                        'Kategorie "%(title)s" wurde erstellt.',
                        title=category.title,
                    )
                )
            case Err(message):
                flash_error(message)
                return category_create_form(party.id, form)

        return redirect_to('.category_index', party_id=party.id)


def register_category_update_routes(blueprint):
    @blueprint.get('/categories/<uuid:category_id>/update')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/category/update_form')
    def category_update_form(category_id, erroneous_form=None):
        category = get_tournament_category_or_404(category_id)
        party = get_party_or_404(category.party_id)
        form = (
            erroneous_form
            if erroneous_form is not None
            else TournamentCategoryForm(data={'title': category.title})
        )
        return {
            'party': party,
            'category': category,
            'form': form,
        }

    @blueprint.post('/categories/<uuid:category_id>')
    @permission_required('netsession_tourney.manage')
    def category_update(category_id):
        category = get_tournament_category_or_404(category_id)
        party = get_party_or_404(category.party_id)

        form = TournamentCategoryForm(request.form)
        if not form.validate():
            return category_update_form(category.id, form)

        match tournament_category_service.update_tournament_category(
            category.id, form.title.data
        ):
            case Ok(updated_category):
                flash_success(
                    gettext(
                        'Kategorie "%(title)s" wurde aktualisiert.',
                        title=updated_category.title,
                    )
                )
            case Err(message):
                flash_error(message)
                return category_update_form(category.id, form)

        return redirect_to('.category_index', party_id=party.id)

    @blueprint.post('/categories/<uuid:category_id>/up')
    @permission_required('netsession_tourney.manage')
    @respond_no_content
    def category_move_up(category_id):
        category = get_tournament_category_or_404(category_id)

        match tournament_category_service.move_tournament_category_up(
            category.id
        ):
            case Ok(_):
                flash_success(gettext('Kategorie wurde nach oben verschoben.'))
            case Err(message):
                flash_error(message)

    @blueprint.post('/categories/<uuid:category_id>/down')
    @permission_required('netsession_tourney.manage')
    @respond_no_content
    def category_move_down(category_id):
        category = get_tournament_category_or_404(category_id)

        match tournament_category_service.move_tournament_category_down(
            category.id
        ):
            case Ok(_):
                flash_success(gettext('Kategorie wurde nach unten verschoben.'))
            case Err(message):
                flash_error(message)

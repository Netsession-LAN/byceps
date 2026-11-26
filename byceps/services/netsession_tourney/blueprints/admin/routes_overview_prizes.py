"""
byceps.services.netsession_tourney.blueprints.admin.routes_overview_prizes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Routes of the tournament prizes (see `routes_overview`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import abort, request
from flask_babel import gettext

from byceps.services.netsession_tourney import (
    tournament_prize_service,
)
from byceps.services.netsession_tourney.forms import (
    TournamentPrizeForm,
)
from byceps.services.netsession_tourney.models import RuleTemplateBodyFormat
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.views import (
    permission_required,
    redirect_to,
)

from .result_helpers import _get_tournament_or_404, get_party_or_404
from .wizard_lookups import (
    get_tournament_prize_or_404,
)


def register_tournament_prize_create_routes(blueprint):
    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/prizes/create'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/prize/create_form')
    def tournament_prize_create_form(
        party_id, tournament_id, erroneous_form=None
    ):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        form = (
            erroneous_form
            if erroneous_form is not None
            else TournamentPrizeForm()
        )

        return {
            'party': party,
            'tournament': tournament,
            'form': form,
        }

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/prizes'
    )
    @permission_required('netsession_tourney.manage')
    def tournament_prize_create(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        form = TournamentPrizeForm(request.form)
        if not form.validate():
            return tournament_prize_create_form(party.id, tournament.id, form)

        match tournament_prize_service.create_tournament_prize(
            tournament.id,
            form.position.data,
            RuleTemplateBodyFormat(form.body_format.data),
            form.body.data,
        ):
            case Ok(prize):
                flash_success(
                    gettext(
                        'Preis für Platz %(position)s wurde erstellt.',
                        position=prize.position,
                    )
                )
            case Err(message):
                flash_error(message)
                return tournament_prize_create_form(
                    party.id, tournament.id, form
                )

        return redirect_to(
            '.view',
            party_id=party.id,
            tournament_id=tournament.id,
            tab='prizes',
        )


def register_tournament_prize_update_routes(blueprint):
    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/prizes/<uuid:prize_id>/update'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/prize/update_form')
    def tournament_prize_update_form(
        party_id, tournament_id, prize_id, erroneous_form=None
    ):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        prize = get_tournament_prize_or_404(prize_id)
        if prize.tournament_id != tournament.id:
            abort(404)

        form = (
            erroneous_form
            if erroneous_form is not None
            else TournamentPrizeForm(
                data={
                    'position': prize.position,
                    'body_format': prize.body_format.value,
                    'body': prize.body,
                }
            )
        )

        return {
            'party': party,
            'tournament': tournament,
            'prize': prize,
            'form': form,
        }

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/prizes/<uuid:prize_id>'
    )
    @permission_required('netsession_tourney.manage')
    def tournament_prize_update(party_id, tournament_id, prize_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        prize = get_tournament_prize_or_404(prize_id)
        if prize.tournament_id != tournament.id:
            abort(404)

        form = TournamentPrizeForm(request.form)
        if not form.validate():
            return tournament_prize_update_form(
                party.id, tournament.id, prize.id, form
            )

        match tournament_prize_service.update_tournament_prize(
            prize.id,
            form.position.data,
            RuleTemplateBodyFormat(form.body_format.data),
            form.body.data,
        ):
            case Ok(updated_prize):
                flash_success(
                    gettext(
                        'Preis für Platz %(position)s wurde aktualisiert.',
                        position=updated_prize.position,
                    )
                )
            case Err(message):
                flash_error(message)
                return tournament_prize_update_form(
                    party.id, tournament.id, prize.id, form
                )

        return redirect_to(
            '.view',
            party_id=party.id,
            tournament_id=tournament.id,
            tab='prizes',
        )


def register_tournament_prize_delete_routes(blueprint):
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/prizes/<uuid:prize_id>/delete'
    )
    @permission_required('netsession_tourney.manage')
    def tournament_prize_delete(party_id, tournament_id, prize_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        prize = get_tournament_prize_or_404(prize_id)
        if prize.tournament_id != tournament.id:
            abort(404)

        match tournament_prize_service.delete_tournament_prize(prize.id):
            case Ok(_):
                flash_success(
                    gettext(
                        'Preis für Platz %(position)s wurde gelöscht.',
                        position=prize.position,
                    )
                )
            case Err(message):
                flash_error(message)

        return redirect_to(
            '.view',
            party_id=party.id,
            tournament_id=tournament.id,
            tab='prizes',
        )

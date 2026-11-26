"""
byceps.services.netsession_tourney.blueprints.admin.routes_participants_entries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Routes to add participants and change their seed and status
(see `routes_participants_matches`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import g, request
from flask_babel import gettext

from byceps.services.netsession_tourney.forms import (
    AdminParticipantAddForm,
    ParticipantDisqualifyForm,
    ParticipantSeedForm,
    ParticipantStatusForm,
)
from byceps.services.netsession_tourney.models import ParticipantStatus
from byceps.services.netsession_tourney.participant_admin_service import (
    add_user_participant_by_admin,
    disqualify_participant,
    remove_participant_by_admin,
    set_participant_status,
)
from byceps.services.netsession_tourney.seed_service import set_participant_seed
from byceps.services.user import user_service
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.result import Err, Ok
from byceps.util.views import permission_required

from .result_helpers import (
    _get_tournament_or_404,
    get_party_or_404,
)
from .result_redirects import (
    redirect_to_participant_or_tournament_view,
    redirect_to_related_tournament_view,
)


def register_participant_add_routes(blueprint):
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/participants/add'
    )
    @permission_required('netsession_tourney.manage')
    def participant_add(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = AdminParticipantAddForm(request.form)
        if not form.validate():
            flash_error(gettext('Ungültige Teilnehmerdaten.'))
            return redirect_to_related_tournament_view(party.id, tournament.id)

        screen_name = form.screen_name.data.strip()
        participant_user = user_service.find_user_by_screen_name(screen_name)
        if participant_user is None:
            flash_error(gettext('Unbekannter Benutzer.'))
            return redirect_to_related_tournament_view(party.id, tournament.id)

        match add_user_participant_by_admin(
            party.id,
            tournament.id,
            participant_user,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(gettext('Teilnehmer wurde hinzugefügt.'))
            case Err(message):
                flash_error(message)

        return redirect_to_related_tournament_view(party.id, tournament.id)


def register_participant_seed_status_routes(blueprint):
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/participants/<uuid:participant_id>/seed'
    )
    @permission_required('netsession_tourney.manage')
    def participant_set_seed(party_id, tournament_id, participant_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = ParticipantSeedForm(request.form)
        if not form.validate():
            flash_error(gettext('Ungültiger Setzplatz.'))
            return redirect_to_participant_or_tournament_view(
                party.id, tournament.id, participant_id
            )

        match set_participant_seed(
            party.id,
            tournament.id,
            participant_id,
            form.seed.data,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(gettext('Setzplatz wurde gespeichert.'))
            case Err(message):
                flash_error(message)

        return redirect_to_participant_or_tournament_view(
            party.id, tournament.id, participant_id
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/participants/<uuid:participant_id>/status'
    )
    @permission_required('netsession_tourney.manage')
    def participant_set_status(party_id, tournament_id, participant_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = ParticipantStatusForm(request.form)
        if not form.validate():
            flash_error(gettext('Ungültiger Status.'))
            return redirect_to_participant_or_tournament_view(
                party.id, tournament.id, participant_id
            )

        status = ParticipantStatus(form.status.data)
        match set_participant_status(
            party.id,
            tournament.id,
            participant_id,
            status,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(
                    gettext('Status des Teilnehmers wurde gespeichert.')
                )
            case Err(message):
                flash_error(message)

        return redirect_to_participant_or_tournament_view(
            party.id, tournament.id, participant_id
        )


def register_participant_removal_routes(blueprint):
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/participants/<uuid:participant_id>/disqualify'
    )
    @permission_required('netsession_tourney.manage')
    def participant_disqualify(party_id, tournament_id, participant_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = ParticipantDisqualifyForm(request.form)
        if not form.validate():
            flash_error(gettext('Ungültige Angaben zur Disqualifikation.'))
            return redirect_to_participant_or_tournament_view(
                party.id, tournament.id, participant_id
            )

        match disqualify_participant(
            party.id,
            tournament.id,
            participant_id,
            g.user.as_user(),
            reason_code=form.reason_code.data,
            comment=form.comment.data,
            correlation_id=request.headers.get('X-Correlation-ID'),
        ):
            case Ok(_):
                flash_success(gettext('Teilnehmer wurde disqualifiziert.'))
            case Err(message):
                flash_error(message)

        return redirect_to_participant_or_tournament_view(
            party.id, tournament.id, participant_id
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/participants/<uuid:participant_id>/remove'
    )
    @permission_required('netsession_tourney.manage')
    def participant_remove(party_id, tournament_id, participant_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        comment = (request.form.get('comment') or '').strip()
        match remove_participant_by_admin(
            party.id,
            tournament.id,
            participant_id,
            g.user.as_user(),
            comment=comment,
        ):
            case Ok(_):
                flash_success(gettext('Teilnehmer wurde entfernt.'))
            case Err(message):
                flash_error(message)

        return redirect_to_participant_or_tournament_view(
            party.id, tournament.id, participant_id
        )

"""
byceps.services.netsession_tourney.blueprints.admin.routes_matches_edit
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Routes to edit matches: slots, host, walkover, result deletion,
schedule and disputes (see `routes_participants_matches`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from uuid import UUID

from flask import g, request
from flask_babel import gettext, to_utc

from byceps.services.netsession_tourney.flatout2_rounds import (
    set_flatout2_match_host_by_admin,
)
from byceps.services.netsession_tourney.forms import (
    MatchDisputeForm,
    MatchScheduleForm,
    MatchWalkoverForm,
)
from byceps.services.netsession_tourney.match_schedule import reschedule_match
from byceps.services.netsession_tourney.result_deletion import (
    delete_match_result_by_admin,
    open_match_dispute,
)
from byceps.services.netsession_tourney.result_service import (
    apply_walkover_result,
)
from byceps.services.netsession_tourney.slot_assignment import (
    set_match_slot_participant_by_admin,
)
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.result import Err, Ok
from byceps.util.views import permission_required

from .result_helpers import (
    _get_tournament_or_404,
    get_or_create_idempotency_key,
    get_party_or_404,
)
from .result_redirects import (
    redirect_to_match_or_tournament_view,
)


def register_match_slot_host_routes(blueprint):
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/slots/<int:slot_no>'
    )
    @permission_required('netsession_tourney.manage')
    def match_slot_set(party_id, tournament_id, match_id, slot_no):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        raw_participant_id = (request.form.get('participant_id') or '').strip()
        participant_id = None
        if raw_participant_id:
            try:
                participant_id = UUID(raw_participant_id)
            except ValueError:
                flash_error(gettext('Ungültiger Teilnehmer.'))
                return redirect_to_match_or_tournament_view(
                    party.id, tournament.id, match_id
                )

        comment = (request.form.get('comment') or '').strip() or None
        match set_match_slot_participant_by_admin(
            party.id,
            tournament.id,
            match_id,
            slot_no,
            participant_id,
            g.user.as_user(),
            comment=comment,
        ):
            case Ok(_):
                flash_success(gettext('Match-Slot wurde aktualisiert.'))
            case Err(message):
                flash_error(message)

        return redirect_to_match_or_tournament_view(
            party.id, tournament.id, match_id
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/host'
    )
    @permission_required('netsession_tourney.manage')
    def match_host_set(party_id, tournament_id, match_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        raw_host_participant_id = (
            request.form.get('host_participant_id') or ''
        ).strip()
        host_participant_id = None
        if raw_host_participant_id:
            try:
                host_participant_id = UUID(raw_host_participant_id)
            except ValueError:
                flash_error(gettext('Ungültiger Host.'))
                return redirect_to_match_or_tournament_view(
                    party.id, tournament.id, match_id
                )

        match set_flatout2_match_host_by_admin(
            party.id,
            tournament.id,
            match_id,
            host_participant_id,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(gettext('FlatOut-2-Host wurde aktualisiert.'))
            case Err(message):
                flash_error(message)

        return redirect_to_match_or_tournament_view(
            party.id, tournament.id, match_id
        )


def register_match_walkover_routes(blueprint):
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/walkover'
    )
    @permission_required('netsession_tourney.manage')
    def match_set_walkover(party_id, tournament_id, match_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = MatchWalkoverForm(request.form)
        if not form.validate():
            flash_error(gettext('Ungültige Daten für den kampflosen Sieg.'))
            return redirect_to_match_or_tournament_view(
                party.id, tournament.id, match_id
            )

        idempotency_key = get_or_create_idempotency_key(
            form.idempotency_key.data
        )

        match apply_walkover_result(
            party.id,
            tournament.id,
            match_id,
            g.user.as_user(),
            winner_slot=form.winner_slot.data,
            idempotency_key=idempotency_key,
            comment=form.comment.data,
            correlation_id=request.headers.get('X-Correlation-ID'),
        ):
            case Ok(_):
                flash_success(gettext('Kampfloser Sieg wurde gespeichert.'))
            case Err(message):
                flash_error(message)

        return redirect_to_match_or_tournament_view(
            party.id, tournament.id, match_id
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/result/delete'
    )
    @permission_required('netsession_tourney.manage')
    def match_delete_result(party_id, tournament_id, match_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        match delete_match_result_by_admin(
            party.id,
            tournament.id,
            match_id,
            g.user.as_user(),
        ):
            case Ok(_):
                flash_success(gettext('Ergebnis wurde gelöscht.'))
            case Err(message):
                flash_error(message)

        return redirect_to_match_or_tournament_view(
            party.id, tournament.id, match_id
        )


def register_match_schedule_dispute_routes(blueprint):
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/reschedule'
    )
    @permission_required('netsession_tourney.manage')
    def match_reschedule(party_id, tournament_id, match_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = MatchScheduleForm(request.form)
        if not form.validate():
            flash_error(gettext('Ungültige Planungsdaten.'))
            return redirect_to_match_or_tournament_view(
                party.id, tournament.id, match_id
            )

        match reschedule_match(
            party.id,
            tournament.id,
            match_id,
            to_utc(form.scheduled_at.data),
            g.user.as_user(),
            comment=form.comment.data,
            correlation_id=request.headers.get('X-Correlation-ID'),
        ):
            case Ok(_):
                flash_success(gettext('Match wurde neu angesetzt.'))
            case Err(message):
                flash_error(message)

        return redirect_to_match_or_tournament_view(
            party.id, tournament.id, match_id
        )

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/matches/<uuid:match_id>/dispute'
    )
    @permission_required('netsession_tourney.manage')
    def match_dispute(party_id, tournament_id, match_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)

        form = MatchDisputeForm(request.form)
        if not form.validate():
            flash_error(gettext('Ungültige Streitfall-Daten.'))
            return redirect_to_match_or_tournament_view(
                party.id, tournament.id, match_id
            )

        match open_match_dispute(
            party.id,
            tournament.id,
            match_id,
            g.user.as_user(),
            reason_code=form.reason_code.data,
            comment=form.comment.data,
            correlation_id=request.headers.get('X-Correlation-ID'),
        ):
            case Ok(_):
                flash_success(gettext('Streitfall wurde eröffnet.'))
            case Err(message):
                flash_error(message)

        return redirect_to_match_or_tournament_view(
            party.id, tournament.id, match_id
        )

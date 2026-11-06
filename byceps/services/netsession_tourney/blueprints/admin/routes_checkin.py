"""
byceps.services.netsession_tourney.blueprints.admin.routes_checkin
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Admins check participants in by hand (or take a check-in back).
"""

from __future__ import annotations

from uuid import UUID

from flask import g, request
from flask_babel import gettext

from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.result import Err, Ok
from byceps.util.views import permission_required

from ...checkin_service import set_checkin_by_admin
from .result_helpers import (
    get_party_or_404,
    _get_tournament_or_404,
    redirect_to_related_tournament_view,
)


def register(blueprint) -> None:
    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>'
        '/participants/<uuid:participant_id>/checkin'
    )
    @permission_required('netsession_tourney.manage')
    def participant_set_checkin(party_id, tournament_id, participant_id: UUID):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        checked_in = request.form.get('checked_in') == '1'

        match set_checkin_by_admin(
            party.id, tournament.id, participant_id, checked_in, g.user.as_user()
        ):
            case Ok(participant):
                flash_success(
                    gettext('%(name)s ist eingecheckt.', name=participant.name)
                    if checked_in
                    else gettext(
                        'Check-in von %(name)s zurückgenommen.',
                        name=participant.name,
                    )
                )
            case Err(message):
                flash_error(message)

        return redirect_to_related_tournament_view(party.id, tournament.id)

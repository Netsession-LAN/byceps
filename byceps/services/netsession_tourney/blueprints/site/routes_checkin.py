"""
byceps.services.netsession_tourney.blueprints.site.routes_checkin
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Check-in of a player or team on the tournament page.
"""

from flask import g
from flask_babel import gettext

from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.result import Err, Ok
from byceps.util.views import login_required, redirect_to

from ...checkin_service import check_in, get_checkin_phase


def register(blueprint, get_tournament_or_404) -> None:
    blueprint.add_app_template_filter(_checkin_phase_name, 'ns_checkin_phase')

    @blueprint.post('/<slug>/checkin')
    @login_required
    def check_in_participant(slug):
        tournament = get_tournament_or_404(slug)
        match check_in(g.party.id, tournament.id, g.user.as_user()):
            case Ok(_):
                flash_success(gettext('Du bist eingecheckt.'))
            case Err(message):
                flash_error(message)
        return redirect_to('.view_overview', slug=slug)


def _checkin_phase_name(tournament) -> str:
    """'before', 'open', 'closed' or '' (no check-in)."""
    phase = get_checkin_phase(tournament)
    return phase.value if phase is not None else ''


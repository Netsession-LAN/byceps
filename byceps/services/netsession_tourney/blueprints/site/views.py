"""
byceps.services.netsession_tourney.blueprints.site.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Public pages of the tournament system. The routes live in the
`routes_*` modules; importing them registers them on the blueprint.
"""

from . import (  # noqa: F401 (the imports register the routes)
    routes_bracket,
    routes_index,
    routes_match,
    routes_pages,
    routes_preliminaries,
    routes_teams,
)
from . import routes_checkin
from .blueprint import blueprint
from .common import _get_tournament_or_404
from .match_state_labels import register_filters


register_filters(blueprint)
routes_checkin.register(blueprint, _get_tournament_or_404)

__all__ = ['blueprint']

"""
byceps.services.netsession_tourney.blueprints.admin.routes_tournament
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.blueprints.admin.routes_tournament_actions import (
    register_participant_view_routes,
    register_tournament_delete_routes,
    register_tournament_notification_routes,
    register_tournament_status_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_tournament_match_view import (
    register_match_view_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_tournament_update import (
    register_tournament_update_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_tournament_view import (
    register_tournament_view_routes,
)


def register(blueprint):
    register_tournament_view_routes(blueprint)
    register_tournament_notification_routes(blueprint)
    register_participant_view_routes(blueprint)
    register_match_view_routes(blueprint)
    register_tournament_update_routes(blueprint)
    register_tournament_status_routes(blueprint)
    register_tournament_delete_routes(blueprint)

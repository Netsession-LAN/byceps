"""
byceps.services.netsession_tourney.blueprints.admin.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.util.framework.blueprint import create_blueprint

from . import routes_create
from . import routes_overview
from . import routes_participants_matches
from . import routes_stage_management
from . import routes_tournament


blueprint = create_blueprint('netsession_tourney_admin', __name__)

routes_overview.register(blueprint)
routes_create.register(blueprint)
routes_tournament.register(blueprint)
routes_stage_management.register(blueprint)
routes_participants_matches.register(blueprint)

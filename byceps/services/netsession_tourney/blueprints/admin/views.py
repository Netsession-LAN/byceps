"""
byceps.services.netsession_tourney.blueprints.admin.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.util.framework.blueprint import create_blueprint

from ...enum_labels import enum_label

from . import routes_create
from . import routes_overview
from . import routes_participants_matches
from . import routes_stage_management
from . import routes_tournament


blueprint = create_blueprint('netsession_tourney_admin', __name__)
blueprint.add_app_template_filter(enum_label, 'ns_label')

routes_overview.register(blueprint)
routes_create.register(blueprint)
routes_tournament.register(blueprint)
routes_stage_management.register(blueprint)
routes_participants_matches.register(blueprint)

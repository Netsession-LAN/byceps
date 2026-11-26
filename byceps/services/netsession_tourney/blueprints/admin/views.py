"""
byceps.services.netsession_tourney.blueprints.admin.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.metrics.metrics_service import register_metric_collector
from byceps.services.netsession_tourney.blueprints.assets import (
    create_assets_blueprint,
)
from byceps.services.netsession_tourney.display_filters import (
    format_ns_datetime,
    raw_enum_label,
    status_class,
)
from byceps.services.netsession_tourney.enum_labels import (
    enum_label,
    report_mode_label,
)
from byceps.services.netsession_tourney.metrics_service import collect_metrics
from byceps.util.framework.blueprint import create_blueprint

from . import (
    routes_checkin,
    routes_create,
    routes_overview,
    routes_participants_matches,
    routes_stage_management,
    routes_tournament,
)
from .result_helpers import get_dropped_participants, get_round_neighbours


blueprint = create_blueprint('netsession_tourney_admin', __name__)
blueprint.register_blueprint(create_assets_blueprint())
blueprint.add_app_template_filter(enum_label, 'ns_label')
blueprint.record_once(
    lambda state: register_metric_collector(state.app, collect_metrics)
)
blueprint.add_app_template_filter(report_mode_label, 'ns_report_mode')
blueprint.add_app_template_global(
    get_dropped_participants, 'ns_dropped_participants'
)
blueprint.add_app_template_filter(format_ns_datetime, 'ns_datetime')
blueprint.add_app_template_filter(raw_enum_label, 'ns_raw_label')
blueprint.add_app_template_filter(status_class, 'ns_status_class')
blueprint.add_app_template_global(get_round_neighbours, 'ns_round_neighbours')

routes_overview.register(blueprint)
routes_create.register(blueprint)
routes_tournament.register(blueprint)
routes_stage_management.register(blueprint)
routes_participants_matches.register(blueprint)
routes_checkin.register(blueprint)

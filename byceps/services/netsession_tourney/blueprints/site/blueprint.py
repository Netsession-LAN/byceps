"""
byceps.services.netsession_tourney.blueprints.site.blueprint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The blueprint of the public tournament pages.
"""

from byceps.services.netsession_tourney.blueprints.assets import (
    create_assets_blueprint,
)
from byceps.util.framework.blueprint import create_blueprint


blueprint = create_blueprint('netsession_tourney', __name__)
blueprint.register_blueprint(create_assets_blueprint())

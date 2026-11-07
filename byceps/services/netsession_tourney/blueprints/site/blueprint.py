"""
byceps.services.netsession_tourney.blueprints.site.blueprint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The blueprint of the public tournament pages.
"""

from byceps.util.framework.blueprint import create_blueprint

from ..assets import create_assets_blueprint


blueprint = create_blueprint('netsession_tourney', __name__)
blueprint.register_blueprint(create_assets_blueprint())

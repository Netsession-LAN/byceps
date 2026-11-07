"""
byceps.services.netsession_tourney.blueprints.assets
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Static files used by both the public and the admin tournament pages
(bracket and Swiss board scripts). Registered as a nested blueprint
`assets` under the site and the admin blueprint, served at
`<prefix>/assets/<filename>`.
"""

from flask import Blueprint


# Bump when a file below changes: Cloudflare caches static files.
ASSET_VERSION = '20261107c'


def create_assets_blueprint() -> Blueprint:
    blueprint = Blueprint(
        'assets', __name__, static_folder='static', static_url_path='/assets'
    )

    @blueprint.app_context_processor
    def inject_asset_version():
        return {'ns_tourney_asset_version': ASSET_VERSION}

    return blueprint

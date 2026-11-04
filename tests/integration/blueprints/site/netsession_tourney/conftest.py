"""Netsession: site app with the tournament system switched on.

The shared `site_app` fixture builds the app with the default config, in
which `netsession_tourney_enabled` is off, so `/ns-tourneys` would not be
registered.
"""

from dataclasses import replace

import pytest

from byceps.application import create_site_app
from byceps.byceps_app import BycepsApp
from byceps.config.models import SiteWebAppConfig
from byceps.services.site.models import Site


@pytest.fixture(scope='module')
def site_app(admin_app, make_byceps_config, site: Site) -> BycepsApp:
    byceps_config = replace(
        make_byceps_config(), netsession_tourney_enabled=True
    )
    app_config = SiteWebAppConfig(
        server_name='www.acmecon.test', site_id=site.id
    )
    app = create_site_app(byceps_config, app_config)
    with app.app_context():
        return app

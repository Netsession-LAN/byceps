"""Netsession: admin app with the tournament system switched on.

The shared `admin_app` fixture builds the app with the default config, in
which `netsession_tourney_enabled` is off, so `/ns-tourneys` would not be
registered.
"""

from dataclasses import replace

import pytest

from byceps.application import create_admin_app
from byceps.config.models import AdminWebAppConfig

# Import the blueprint outside of any app context: its route config calls
# `gettext` at import time, which needs `g.user` inside an app context.
import byceps.services.netsession_tourney.blueprints.admin.views  # noqa: F401

from tests.helpers import log_in_user


ADMIN_BASE_URL = 'http://admin.acmecon.test/ns-tourneys'

ALL_TOURNEY_PERMISSIONS = {
    'admin.access',
    'netsession_tourney.view',
    'netsession_tourney.participate',
    'netsession_tourney.report_result',
    'netsession_tourney.manage',
    'netsession_tourney.admin',
}


@pytest.fixture(scope='package')
def tourney_admin_app(admin_app, make_byceps_config):
    """Depends on `admin_app` so that its app context is pushed first."""
    byceps_config = replace(
        make_byceps_config(), netsession_tourney_enabled=True
    )
    app = create_admin_app(
        byceps_config, AdminWebAppConfig(server_name='admin.acmecon.test')
    )
    with app.app_context():
        yield app


@pytest.fixture(scope='package')
def make_tourney_client(tourney_admin_app, make_admin, make_client):
    """Return a client of an admin with the given permissions."""

    def _wrapper(permissions: set[str]):
        admin = make_admin(permissions)
        log_in_user(admin.id)
        return make_client(tourney_admin_app, user_id=admin.id)

    return _wrapper


@pytest.fixture(scope='package')
def tourney_admin(tourney_admin_app, make_admin):
    admin = make_admin(ALL_TOURNEY_PERMISSIONS)
    log_in_user(admin.id)
    return admin


@pytest.fixture(scope='package')
def tourney_admin_client(tourney_admin_app, tourney_admin, make_client):
    return make_client(tourney_admin_app, user_id=tourney_admin.id)


@pytest.fixture(scope='package')
def tourney_viewer_client(make_tourney_client):
    """May view, but not manage tournaments."""
    return make_tourney_client({'admin.access', 'netsession_tourney.view'})


@pytest.fixture(scope='package')
def plain_admin_client(make_tourney_client):
    """May open the admin app, but has no tournament permissions."""
    return make_tourney_client({'admin.access'})


@pytest.fixture(scope='module')
def tourney_party(make_party, brand):
    """A party of its own per module keeps wizard state and data apart."""
    return make_party(brand)


@pytest.fixture(scope='package')
def pop_flashes():
    """Return the texts of the flashed messages and remove them."""

    def _wrapper(client) -> list[str]:
        with client.session_transaction() as session:
            flashes = session.pop('_flashes', [])
        return [_flash_text(message) for _category, message in flashes]

    return _wrapper


def _flash_text(message) -> str:
    if isinstance(message, dict):
        return message.get('text', '')
    return getattr(message, 'text', str(message))

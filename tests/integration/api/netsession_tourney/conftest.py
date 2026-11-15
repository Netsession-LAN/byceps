"""Fixtures for the Netsession tournament API."""

from dataclasses import replace

import pytest

from byceps.application import create_api_app
from byceps.config.models import ApiWebAppConfig
from byceps.services.authn.api import authn_api_service
from byceps.services.authz.models import PermissionID


@pytest.fixture(scope='module')
def ns_api_client(admin_app, make_byceps_config):
    byceps_config = replace(
        make_byceps_config(), netsession_tourney_enabled=True
    )
    app = create_api_app(
        byceps_config, ApiWebAppConfig(server_name='api.ns.test')
    )
    return app.test_client()


@pytest.fixture(scope='module')
def read_headers(admin_user):
    token = authn_api_service.create_api_token(
        admin_user.id, {PermissionID('ns_api.read')}
    )
    return {'Authorization': f'Bearer {token.token}'}


@pytest.fixture(scope='module')
def other_headers(admin_user):
    token = authn_api_service.create_api_token(admin_user.id, set())
    return {'Authorization': f'Bearer {token.token}'}

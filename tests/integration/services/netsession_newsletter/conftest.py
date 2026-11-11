"""Fixtures for the Netsession newsletter sync module."""

from datetime import datetime

import pytest

from byceps.services.authn.api import authn_api_service
from byceps.services.authz.models import PermissionID
from byceps.services.newsletter import newsletter_command_service
from byceps.services.newsletter.models import ListID

from tests.helpers import generate_token


@pytest.fixture()
def newsletter_list():
    list_id = ListID(f'ns-{generate_token(8).lower()}')
    return newsletter_command_service.create_list(list_id, 'Netsession')


@pytest.fixture()
def subscribe():
    def _wrapper(user, list_):
        newsletter_command_service.subscribe_user_to_list(
            user, list_, datetime(2026, 2, 24, 10, 0), user
        ).unwrap()

    return _wrapper


@pytest.fixture(scope='module')
def sync_authz_header(admin_user):
    token = authn_api_service.create_api_token(
        admin_user.id, {PermissionID('ns_newsletter.sync')}
    )
    return 'Authorization', f'Bearer {token.token}'


@pytest.fixture(scope='module')
def other_authz_header(admin_user):
    token = authn_api_service.create_api_token(admin_user.id, set())
    return 'Authorization', f'Bearer {token.token}'

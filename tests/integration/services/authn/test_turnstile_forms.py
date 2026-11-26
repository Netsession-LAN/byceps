"""
:Copyright: 2025-2026 Kevin Lehmann
:License: Revised BSD (see `LICENSE` file for details)
"""

import httpx
import pytest

from byceps.config.models import CloudflareTurnstileConfig
from byceps.util import turnstile


CONFIG = CloudflareTurnstileConfig(
    enabled=True,
    sitekey='turnstile-sitekey',
    secret_key='turnstile-secret-key',
)

SITE_SERVER_NAME = 'turnstile.acmecon.test'
ADMIN_SERVER_NAME = 'turnstile-admin.acmecon.test'

PASSWORD = 'turnstile-test-password'


@pytest.fixture(scope='module')
def turnstile_site_app(make_site_app, site):
    return make_site_app(SITE_SERVER_NAME, site.id, cloudflare_turnstile=CONFIG)


@pytest.fixture(scope='module')
def turnstile_admin_app(make_admin_app):
    return make_admin_app(ADMIN_SERVER_NAME, cloudflare_turnstile=CONFIG)


@pytest.mark.parametrize(
    ('path', 'action'),
    [
        ('/authentication/log_in', 'login'),
        ('/users/create', 'user_create'),
        (
            '/authentication/password/reset/request',
            'password_reset_request',
        ),
        (
            '/users/email_address/confirmation_email/request',
            'email_confirmation_request',
        ),
    ],
)
def test_site_form_renders_widget(turnstile_site_app, site_app, path, action):
    response = turnstile_site_app.test_client().get(
        f'http://{SITE_SERVER_NAME}{path}'
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f'data-sitekey="turnstile-sitekey" data-action="{action}"' in body
    assert body.count('challenges.cloudflare.com/turnstile/v0/api.js') == 1

    # Without configuration, the widget is not rendered.
    response = site_app.test_client().get(f'http://www.acmecon.test{path}')
    assert response.status_code == 200
    assert 'turnstile' not in response.get_data(as_text=True)


def test_admin_password_reset_form_renders_widget(turnstile_admin_app):
    response = turnstile_admin_app.test_client().get(
        f'http://{ADMIN_SERVER_NAME}/authentication/password/reset/request'
    )
    assert response.status_code == 200
    assert 'data-action="password_reset_request"' in response.get_data(
        as_text=True
    )


@pytest.fixture(scope='module')
def user(make_user):
    return make_user(password=PASSWORD)


@pytest.fixture
def siteverify(respx_mock):
    return respx_mock.post(turnstile.VERIFY_URL)


def log_in(app, user, token: str | None = None) -> int:
    data = {'username': user.screen_name, 'password': PASSWORD}
    if token is not None:
        data['cf-turnstile-response'] = token

    response = app.test_client().post(
        f'http://{SITE_SERVER_NAME}/authentication/log_in', data=data
    )
    return response.status_code


def test_log_in_with_valid_token(turnstile_site_app, user, siteverify):
    siteverify.respond(json={'success': True, 'action': 'login'})

    assert log_in(turnstile_site_app, user, 'valid-token') == 204


def test_log_in_with_invalid_token(turnstile_site_app, user, siteverify):
    siteverify.respond(json={'success': False})

    assert log_in(turnstile_site_app, user, 'bogus-token') == 401


def test_log_in_without_token(turnstile_site_app, user, siteverify):
    siteverify.respond(json={'success': True})

    assert log_in(turnstile_site_app, user) == 401


def test_log_in_with_token_for_other_form(turnstile_site_app, user, siteverify):
    siteverify.respond(json={'success': True, 'action': 'user_create'})

    assert log_in(turnstile_site_app, user, 'valid-token') == 401


def test_log_in_without_token_while_cloudflare_is_down(
    turnstile_site_app, user, siteverify
):
    siteverify.side_effect = httpx.ConnectTimeout('Cloudflare unreachable')

    assert log_in(turnstile_site_app, user) == 204

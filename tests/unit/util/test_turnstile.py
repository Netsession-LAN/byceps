"""
:Copyright: 2025-2026 Kevin Lehmann
:License: Revised BSD (see `LICENSE` file for details)
"""

import dataclasses
from urllib.parse import parse_qs

from flask import Flask
import httpx
import pytest

from byceps.config.models import CloudflareTurnstileConfig
from byceps.util import turnstile


CONFIG = CloudflareTurnstileConfig(
    enabled=True,
    sitekey='site-key',
    secret_key='secret-key',
)


@pytest.fixture
def siteverify(respx_mock):
    return respx_mock.post(turnstile.VERIFY_URL)


def sent_data(route) -> dict[str, str]:
    content = route.calls.last.request.content.decode()
    return {key: values[0] for key, values in parse_qs(content).items()}


def test_verify_token_rejects_invalid_token(siteverify):
    siteverify.respond(json={'success': False})

    assert not turnstile.verify_token(CONFIG, 'bogus')

    assert siteverify.call_count == 1
    data = sent_data(siteverify)
    assert data['secret'] == 'secret-key'
    assert data['response'] == 'bogus'


def test_verify_token_accepts_valid_token(siteverify):
    siteverify.respond(json={'success': True, 'action': 'login'})

    assert turnstile.verify_token(
        CONFIG, 'valid', remote_ip='192.0.2.1', expected_action='login'
    )

    assert sent_data(siteverify)['remoteip'] == '192.0.2.1'


def test_verify_token_rejects_other_action(siteverify):
    siteverify.respond(json={'success': True, 'action': 'user_create'})

    assert not turnstile.verify_token(CONFIG, 'valid', expected_action='login')


def test_verify_token_rejects_missing_token(siteverify):
    siteverify.respond(json={'success': True})

    assert not turnstile.verify_token(CONFIG, '')

    # Cloudflare is asked anyway to find out whether it is reachable.
    assert siteverify.call_count == 1


def test_verify_token_rejects_without_secret_key(siteverify):
    config = CloudflareTurnstileConfig(
        enabled=True, sitekey='site-key', secret_key=''
    )

    assert not turnstile.verify_token(config, 'valid')

    assert siteverify.call_count == 0


@pytest.mark.parametrize('token', ['some-token', ''])
def test_verify_token_lets_through_when_cloudflare_is_down(siteverify, token):
    # An outage of Cloudflare must not lock everybody out.
    siteverify.side_effect = httpx.ConnectError('Cloudflare unreachable')

    assert turnstile.verify_token(CONFIG, token)


@pytest.mark.parametrize(
    'body', ['<html>Bad Gateway</html>', '["success"]', 'null']
)
def test_verify_token_lets_through_on_unusable_answer(siteverify, body):
    siteverify.respond(200, text=body)

    assert turnstile.verify_token(CONFIG, 'some-token')


def test_verify_token_lets_through_on_server_error(siteverify):
    siteverify.respond(502, text='Bad Gateway')

    assert turnstile.verify_token(CONFIG, 'some-token')


@pytest.fixture
def app():
    return Flask(__name__)


def test_verify_request_passes_when_disabled(app, monkeypatch, siteverify):
    monkeypatch.setattr(turnstile, 'get_enabled_config', lambda: None)

    with app.test_request_context('/form', method='POST', data={}):
        assert turnstile.verify_request('login')

    assert siteverify.call_count == 0


@pytest.mark.parametrize(
    ('response_data', 'form_data', 'expected'),
    [
        ({'success': True}, {'cf-turnstile-response': 'valid'}, True),
        ({'success': False}, {'cf-turnstile-response': 'bogus'}, False),
        # No token is rejected even if Cloudflare said otherwise.
        ({'success': True}, {}, False),
    ],
)
def test_verify_request(
    app, monkeypatch, siteverify, response_data, form_data, expected
):
    monkeypatch.setattr(turnstile, 'get_enabled_config', lambda: CONFIG)
    siteverify.respond(json=response_data)

    with app.test_request_context('/form', method='POST', data=form_data):
        assert turnstile.verify_request('login') == expected


def test_verify_request_without_token_passes_when_cloudflare_is_down(
    app, monkeypatch, siteverify
):
    # The widget cannot load during an outage, so there is no token.
    monkeypatch.setattr(turnstile, 'get_enabled_config', lambda: CONFIG)
    siteverify.side_effect = httpx.ConnectError('Cloudflare unreachable')

    with app.test_request_context('/form', method='POST', data={}):
        assert turnstile.verify_request('login')


def test_get_sitekey(monkeypatch):
    monkeypatch.setattr(turnstile, 'get_enabled_config', lambda: CONFIG)
    assert turnstile.get_sitekey() == 'site-key'

    monkeypatch.setattr(turnstile, 'get_enabled_config', lambda: None)
    assert turnstile.get_sitekey() is None

    config = CloudflareTurnstileConfig(
        enabled=True, sitekey='', secret_key='secret-key'
    )
    monkeypatch.setattr(turnstile, 'get_enabled_config', lambda: config)
    assert turnstile.get_sitekey() is None


@pytest.mark.parametrize(
    ('config', 'expected'),
    [
        (None, None),
        (
            CloudflareTurnstileConfig(
                enabled=False, sitekey='site-key', secret_key='secret-key'
            ),
            None,
        ),
        (CONFIG, CONFIG),
    ],
)
def test_get_enabled_config(make_byceps_config, config, expected):
    app = Flask(__name__)
    app.byceps_config = dataclasses.replace(
        make_byceps_config(), cloudflare_turnstile=config
    )

    with app.app_context():
        assert turnstile.get_enabled_config() == expected

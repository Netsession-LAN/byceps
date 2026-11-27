"""Netsession: tests for the Cloudflare Turnstile verification."""

import httpx
from flask import Flask
import pytest

from byceps.util import turnstile


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config['CLOUDFLARE_TURNSTILE'] = {
        'enabled': True,
        'sitekey': 'site-key',
        'secret_key': 'secret-key',
    }
    return app


def _fake_post(payload, calls):
    def fake_post(url, *, data, timeout):
        calls.append((url, data))
        request = httpx.Request('POST', url)
        return httpx.Response(200, json=payload, request=request)

    return fake_post


def _patch_post(monkeypatch, fake):
    monkeypatch.setattr(turnstile.httpx, 'post', fake)


def test_verify_token_asks_cloudflare_and_rejects_invalid_token(
    app, monkeypatch
):
    calls = []
    _patch_post(monkeypatch, _fake_post({'success': False}, calls))

    with app.app_context():
        assert not turnstile.verify_token('bogus', remoteip='203.0.113.7')

    assert calls == [
        (
            turnstile.VERIFY_URL,
            {
                'secret': 'secret-key',
                'response': 'bogus',
                'remoteip': '203.0.113.7',
            },
        )
    ]


def test_verify_token_accepts_valid_token(app, monkeypatch):
    calls = []
    _patch_post(monkeypatch, _fake_post({'success': True}, calls))

    with app.app_context():
        assert turnstile.verify_token('valid', expected_action='login')

    assert len(calls) == 1


def test_verify_token_rejects_missing_token(app, monkeypatch):
    calls = []
    _patch_post(monkeypatch, _fake_post({'success': False}, calls))

    with app.app_context():
        assert not turnstile.verify_token('')


def _unreachable(url, *, data, timeout):
    raise httpx.ConnectError('Cloudflare unreachable')


def _server_error(url, *, data, timeout):
    request = httpx.Request('POST', url)
    return httpx.Response(502, text='Bad Gateway', request=request)


@pytest.mark.parametrize('token', ['some-token', ''])
@pytest.mark.parametrize('fake', [_unreachable, _server_error])
def test_verify_token_lets_through_when_cloudflare_is_down(
    app, monkeypatch, token, fake
):
    # Decision 2026-11-06: an outage of Cloudflare must not lock
    # everybody out; it is logged instead.
    _patch_post(monkeypatch, fake)

    with app.app_context():
        assert turnstile.verify_token(token)


def test_verify_token_passes_when_disabled(monkeypatch):
    app = Flask(__name__)
    app.config['CLOUDFLARE_TURNSTILE'] = {'enabled': False}
    calls = []
    _patch_post(monkeypatch, _fake_post({'success': False}, calls))

    with app.app_context():
        assert turnstile.verify_token('anything')

    assert calls == []


def test_request_without_token_passes_when_cloudflare_is_down(app, monkeypatch):
    # The widget does not load during an outage, so the form has no token.
    _patch_post(monkeypatch, _unreachable)

    with app.test_request_context('/form', method='POST', data={}):
        assert turnstile.passes_request('login')


def test_request_without_token_is_refused_when_cloudflare_is_up(
    app, monkeypatch
):
    calls = []
    _patch_post(monkeypatch, _fake_post({'success': False}, calls))

    with app.test_request_context('/form', method='POST', data={}):
        assert not turnstile.passes_request('login')


def test_request_with_valid_token_passes(app, monkeypatch):
    calls = []
    _patch_post(monkeypatch, _fake_post({'success': True}, calls))
    data = {'cf-turnstile-response': 'valid'}

    with app.test_request_context('/form', method='POST', data=data):
        assert turnstile.passes_request('login')

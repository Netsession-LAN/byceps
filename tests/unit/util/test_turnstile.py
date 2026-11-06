"""Netsession: tests for the Cloudflare Turnstile verification."""

import io
import json

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


def _fake_urlopen(payload, calls):
    def fake_urlopen(req, timeout):
        calls.append(req)
        return io.BytesIO(json.dumps(payload).encode('utf-8'))

    return fake_urlopen


def test_verify_token_asks_cloudflare_and_rejects_invalid_token(app, monkeypatch):
    calls = []
    monkeypatch.setattr(
        turnstile, 'urlopen', _fake_urlopen({'success': False}, calls)
    )

    with app.app_context():
        assert not turnstile.verify_token('bogus')

    assert len(calls) == 1


def test_verify_token_accepts_valid_token(app, monkeypatch):
    calls = []
    monkeypatch.setattr(
        turnstile, 'urlopen', _fake_urlopen({'success': True}, calls)
    )

    with app.app_context():
        assert turnstile.verify_token('valid', expected_action='login')

    assert len(calls) == 1


def test_verify_token_rejects_missing_token(app, monkeypatch):
    calls = []
    monkeypatch.setattr(
        turnstile, 'urlopen', _fake_urlopen({'success': False}, calls)
    )

    with app.app_context():
        assert not turnstile.verify_token('')


def _unreachable(req, timeout):
    raise OSError('Cloudflare unreachable')


@pytest.mark.parametrize('token', ['some-token', ''])
def test_verify_token_lets_through_when_cloudflare_is_down(
    app, monkeypatch, token
):
    # Decision 2026-11-06: an outage of Cloudflare must not lock
    # everybody out; it is logged instead.
    monkeypatch.setattr(turnstile, 'urlopen', _unreachable)

    with app.app_context():
        assert turnstile.verify_token(token)


def test_verify_token_passes_when_disabled(monkeypatch):
    app = Flask(__name__)
    app.config['CLOUDFLARE_TURNSTILE'] = {'enabled': False}
    calls = []
    monkeypatch.setattr(
        turnstile, 'urlopen', _fake_urlopen({'success': False}, calls)
    )

    with app.app_context():
        assert turnstile.verify_token('anything')

    assert calls == []


def test_request_without_token_passes_when_cloudflare_is_down(app, monkeypatch):
    # The widget does not load during an outage, so the form has no token.
    monkeypatch.setattr(turnstile, 'urlopen', _unreachable)

    with app.test_request_context('/form', method='POST', data={}):
        assert turnstile.passes_request('login')


def test_request_without_token_is_refused_when_cloudflare_is_up(
    app, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        turnstile, 'urlopen', _fake_urlopen({'success': False}, calls)
    )

    with app.test_request_context('/form', method='POST', data={}):
        assert not turnstile.passes_request('login')


def test_request_with_valid_token_passes(app, monkeypatch):
    calls = []
    monkeypatch.setattr(
        turnstile, 'urlopen', _fake_urlopen({'success': True}, calls)
    )
    data = {'cf-turnstile-response': 'valid'}

    with app.test_request_context('/form', method='POST', data=data):
        assert turnstile.passes_request('login')

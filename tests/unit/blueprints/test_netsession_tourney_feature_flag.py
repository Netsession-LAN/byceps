"""
:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from flask import Flask

from byceps.blueprints import admin as admin_blueprints
from byceps.blueprints import api as api_blueprints
from byceps.blueprints import site as site_blueprints


def test_site_blueprints_do_not_include_netsession_tourney_if_disabled(
    monkeypatch,
):
    app = Flask('byceps-test')
    app.config['NETSESSION_TOURNEY_ENABLED'] = False

    captured = {}

    monkeypatch.setattr(site_blueprints, 'get_common_blueprints', lambda **_: [])
    monkeypatch.setattr(
        site_blueprints,
        'register_blueprints',
        lambda _app, blueprints: captured.setdefault('blueprints', blueprints),
    )

    site_blueprints.register_site_blueprints(app)

    assert (
        'services.netsession_tourney.blueprints.site',
        '/ns-tourneys',
    ) not in captured['blueprints']


def test_site_blueprints_include_netsession_tourney_if_enabled(monkeypatch):
    app = Flask('byceps-test')
    app.config['NETSESSION_TOURNEY_ENABLED'] = True

    captured = {}

    monkeypatch.setattr(site_blueprints, 'get_common_blueprints', lambda **_: [])
    monkeypatch.setattr(
        site_blueprints,
        'register_blueprints',
        lambda _app, blueprints: captured.setdefault('blueprints', blueprints),
    )

    site_blueprints.register_site_blueprints(app)

    assert (
        'services.netsession_tourney.blueprints.site',
        '/ns-tourneys',
    ) in captured['blueprints']


def test_admin_blueprints_include_netsession_tourney_if_enabled(monkeypatch):
    app = Flask('byceps-test')
    app.config['NETSESSION_TOURNEY_ENABLED'] = True

    captured = {}

    monkeypatch.setattr(
        admin_blueprints, 'get_common_blueprints', lambda **_: []
    )
    monkeypatch.setattr(
        admin_blueprints,
        'register_blueprints',
        lambda _app, blueprints: captured.setdefault('blueprints', blueprints),
    )

    admin_blueprints.register_admin_blueprints(app)

    assert (
        'services.netsession_tourney.blueprints.admin',
        '/ns-tourneys',
    ) in captured['blueprints']


def test_api_blueprints_include_netsession_tourney_if_enabled(monkeypatch):
    app = Flask('byceps-test')
    app.config['NETSESSION_TOURNEY_ENABLED'] = True

    captured = {}

    monkeypatch.setattr(
        api_blueprints,
        'register_blueprints',
        lambda _app, blueprints: captured.setdefault('blueprints', blueprints),
    )

    api_blueprints.register_api_blueprints(app)

    assert (
        'services.netsession_tourney.blueprints.api',
        '/ns-tourneys',
    ) in captured['blueprints']


"""The tournament API is public; requests that fail must not each write a
metric row (anybody could fill the table with garbage requests)."""

from dataclasses import replace

import pytest
from sqlalchemy import delete, func, select

from byceps.application import create_api_app
from byceps.config.models import ApiWebAppConfig
from byceps.database import db
from byceps.services.netsession_tourney.dbmodels import (
    DbNetsessionTourneyApiRequestMetric,
)


@pytest.fixture(scope='module')
def ns_api_client(admin_app, make_byceps_config):
    byceps_config = replace(
        make_byceps_config(), netsession_tourney_enabled=True
    )
    app = create_api_app(
        byceps_config, ApiWebAppConfig(server_name='api.ns.test')
    )
    return app.test_client()


def _metric_count() -> int:
    return db.session.scalar(
        select(func.count()).select_from(DbNetsessionTourneyApiRequestMetric)
    )


def test_failing_requests_write_no_metric(ns_api_client, party):
    db.session.execute(delete(DbNetsessionTourneyApiRequestMetric))
    db.session.commit()
    base = 'http://api.ns.test/v1/ns-tourneys/tournaments'

    assert ns_api_client.get(base).status_code == 400
    assert (
        ns_api_client.get(base + '?party_id=no-such-party').status_code == 404
    )
    assert _metric_count() == 0

    assert ns_api_client.get(f'{base}?party_id={party.id}').status_code == 200
    assert _metric_count() == 1

"""Requests that fail must not each write a metric row (anybody could fill
the table with garbage requests)."""

from sqlalchemy import delete, func, select

from byceps.database import db
from byceps.services.netsession_tourney.dbmodels import (
    DbNetsessionTourneyApiRequestMetric,
)


def _metric_count() -> int:
    return db.session.scalar(
        select(func.count()).select_from(DbNetsessionTourneyApiRequestMetric)
    )


def test_failing_requests_write_no_metric(ns_api_client, read_headers, party):
    db.session.execute(delete(DbNetsessionTourneyApiRequestMetric))
    db.session.commit()
    base = 'http://api.ns.test/v1/ns-tourneys/tournaments'

    assert ns_api_client.get(f'{base}?party_id={party.id}').status_code == 401
    assert ns_api_client.get(base, headers=read_headers).status_code == 400
    assert (
        ns_api_client.get(
            base + '?party_id=no-such-party', headers=read_headers
        ).status_code
        == 404
    )
    assert _metric_count() == 0

    assert (
        ns_api_client.get(
            f'{base}?party_id={party.id}', headers=read_headers
        ).status_code
        == 200
    )
    assert _metric_count() == 1

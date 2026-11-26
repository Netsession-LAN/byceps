"""
byceps.services.netsession_tourney.observability_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError
import structlog

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.util.uuid import generate_uuid7

from .dbmodels import DbNetsessionTourneyApiRequestMetric


log = structlog.get_logger()


def record_api_request_metric(
    *,
    endpoint: str,
    method: str,
    status_code: int,
    duration_ms: int,
    party_id: PartyID | None = None,
) -> None:
    db.session.add(
        DbNetsessionTourneyApiRequestMetric(
            generate_uuid7(),
            endpoint,
            method,
            status_code,
            duration_ms,
            datetime.utcnow(),
            party_id=party_id,
        )
    )

    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        log.warning(
            'netsession_tourney.api_metric_record_failed',
            endpoint=endpoint,
            method=method,
            status_code=status_code,
        )

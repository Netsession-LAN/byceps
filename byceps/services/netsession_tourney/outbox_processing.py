"""
byceps.services.netsession_tourney.outbox_processing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Shared row loop of the outbox workers (Discord, Discord DM, browser push).

Every row is committed on its own, so a crash never sends rows again that
were already delivered. An unexpected error in one row parks that row as
dead letter (and logs it) instead of blocking every row after it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

import structlog

from byceps.database import db


log = structlog.get_logger()


def process_outbox_rows(
    db_rows: Sequence[Any],
    deliver_row: Callable[[Any, datetime], None],
    mark_dead_letter: Callable[[Any, str, datetime], None],
    now: datetime,
    *,
    outbox_name: str,
) -> None:
    for db_row in db_rows:
        row_class = type(db_row)
        row_id = db_row.id
        try:
            db_row.attempt_count += 1
            db_row.updated_at = now
            deliver_row(db_row, now)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            log.exception(
                'netsession_tourney.outbox_row_failed',
                outbox=outbox_name,
                row_id=str(row_id),
            )
            _park_failed_row(row_class, row_id, exc, mark_dead_letter, now)


def _park_failed_row(row_class, row_id, exc, mark_dead_letter, now) -> None:
    db_row = db.session.get(row_class, row_id)
    if db_row is None:
        return
    db_row.attempt_count += 1
    mark_dead_letter(db_row, f'Unerwarteter Fehler: {type(exc).__name__}', now)
    db.session.commit()

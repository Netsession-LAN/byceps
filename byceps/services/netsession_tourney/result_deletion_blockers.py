"""
byceps.services.netsession_tourney.result_deletion_blockers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Finding what blocks the deletion of a match result (results in
downstream matches).
"""

from __future__ import annotations

from sqlalchemy import select

from byceps.database import db

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
)
from .models import (
    MatchID,
)


def _get_delete_blocker_error(match_id: MatchID) -> str | None:
    blocking_match_id = find_match_result_delete_blocker(match_id)
    if blocking_match_id is None:
        return None

    db_blocking_match = db.session.get(
        DbNetsessionTourneyMatch, blocking_match_id
    )
    if db_blocking_match is None:
        return 'Das Ergebnis lässt sich nicht löschen, weil ein Folge-Match schon ein gemeldetes Ergebnis hat.'

    return (
        'Das Ergebnis lässt sich nicht löschen, weil ein Folge-Match '
        f'(Runde {db_blocking_match.round_no}, Match {db_blocking_match.match_no}) '
        'schon ein gemeldetes Ergebnis hat.'
    )


def find_match_result_delete_blocker(
    match_id: MatchID, *, visited: set[MatchID] | None = None
) -> MatchID | None:
    if visited is None:
        visited = set()

    source_slot = db.session.scalar(
        select(DbNetsessionTourneyMatchSlot).filter_by(
            match_id=match_id, slot_no=1
        )
    )
    if source_slot is None:
        return None

    downstream_match_ids = _get_downstream_match_ids(source_slot)

    for downstream_match_id in sorted(downstream_match_ids):
        blocking_match_id = _find_delete_blocker_from_downstream_match(
            downstream_match_id, visited
        )
        if blocking_match_id is not None:
            return blocking_match_id

    return None


def _get_downstream_match_ids(
    source_slot: DbNetsessionTourneyMatchSlot,
) -> set[MatchID]:
    return {
        downstream_match_id
        for downstream_match_id in db.session.scalars(
            select(DbNetsessionTourneyMatchSlot.match_id).filter_by(
                source_match_slot_id=source_slot.id
            )
        ).all()
    }


def _find_delete_blocker_from_downstream_match(
    downstream_match_id: MatchID, visited: set[MatchID]
) -> MatchID | None:
    """Return the downstream match itself if a user reported its result,
    else search further downstream (unless already visited)."""
    if downstream_match_id in visited:
        return None

    visited.add(downstream_match_id)
    db_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(
            match_id=downstream_match_id
        )
    )
    if db_result is None:
        return None

    if db_result.submitted_by_user_id is not None:
        return downstream_match_id

    return find_match_result_delete_blocker(
        downstream_match_id, visited=visited
    )

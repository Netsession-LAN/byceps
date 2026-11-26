"""
byceps.services.netsession_tourney.result_reporting_store
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Storing a reported match result: creating it, or updating it when
the reports agree or a winner change is allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select

from byceps.database import db
from byceps.services.user.models import UserID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
)
from .models import (
    MatchID,
    MatchResultID,
)
from .result_deletion_blockers import find_match_result_delete_blocker
from .result_reporting_sides import (
    advance_after_completion as advance_after_completion,
    load_match_sides as load_match_sides,
    MatchSides as MatchSides,
)
from .swiss_correction import prepare_swiss_winner_change


@dataclass(frozen=True, kw_only=True)
class ResultReport:
    """What a player or admin reports for a match."""

    actor_user_id: UserID
    idempotency_key: str
    winner_slot: int | None
    score_data: dict[str, Any]
    ranking_data: dict[str, Any]
    by_admin: bool
    admin_comment: str | None
    reason_code: str | None
    correlation_id: str | None


def store_reported_result(
    match_id: MatchID, report: ResultReport, now: datetime
) -> Result[tuple[DbNetsessionTourneyMatchResult, bool], str]:
    """Create the result, or update it with a further report.

    Returns the result and whether this report agrees with an earlier one
    by the other side.
    """
    db_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(match_id=match_id)
    )
    if db_result is None:
        return Ok((_create_reported_result(match_id, report, now), False))

    reports_agree = _do_reports_agree(db_result, report)

    update_error = _get_reported_result_update_error(
        match_id, db_result, report
    )
    if update_error is not None:
        return Err(update_error)

    _update_reported_result(db_result, report, now)

    return Ok((db_result, reports_agree))


def _create_reported_result(
    match_id: MatchID, report: ResultReport, now: datetime
) -> DbNetsessionTourneyMatchResult:
    db_result = DbNetsessionTourneyMatchResult(
        MatchResultID(generate_uuid7()),
        match_id,
        now,
        winner_slot=report.winner_slot,
        score_json=report.score_data,
        ranking_json=report.ranking_data,
        submitted_by_user_id=report.actor_user_id,
    )
    db.session.add(db_result)
    return db_result


def _do_reports_agree(
    db_result: DbNetsessionTourneyMatchResult, report: ResultReport
) -> bool:
    """Tell whether the report matches the stored one of the other side."""
    return (
        db_result.winner_slot == report.winner_slot
        and db_result.score_json == report.score_data
        and db_result.ranking_json == report.ranking_data
        and db_result.submitted_by_user_id != report.actor_user_id
    )


def _get_reported_result_update_error(
    match_id: MatchID,
    db_result: DbNetsessionTourneyMatchResult,
    report: ResultReport,
) -> str | None:
    if (
        report.by_admin
        and db_result.submitted_by_user_id is not None
        and not report.admin_comment
    ):
        return 'Korrekturen durch Admins brauchen einen Kommentar.'

    return _check_winner_change_allowed(match_id, db_result, report)


def _update_reported_result(
    db_result: DbNetsessionTourneyMatchResult,
    report: ResultReport,
    now: datetime,
) -> None:
    db_result.winner_slot = report.winner_slot
    db_result.score_json = report.score_data
    db_result.ranking_json = report.ranking_data
    db_result.updated_at = now
    if db_result.submitted_by_user_id is None:
        db_result.submitted_by_user_id = report.actor_user_id
    if (
        not report.by_admin
        and db_result.submitted_by_user_id != report.actor_user_id
    ):
        db_result.confirmed_by_user_id = report.actor_user_id


def _check_winner_change_allowed(
    match_id: MatchID,
    db_result: DbNetsessionTourneyMatchResult,
    report: ResultReport,
) -> str | None:
    """A new winner would move other participants into the following
    matches; that is refused once one of them has a reported result (the
    same rule as for deleting a result). Score-only corrections stay
    possible."""
    if (
        db_result.winner_slot is None
        or db_result.winner_slot == report.winner_slot
    ):
        return None

    # Swiss has no follow-up slots; its later rounds are re-paired instead.
    swiss_error = prepare_swiss_winner_change(
        db.session.get(DbNetsessionTourneyMatch, match_id)
    )
    if swiss_error is not None:
        return swiss_error

    blocking_match_id = find_match_result_delete_blocker(match_id)
    if blocking_match_id is None:
        return None

    db_blocking_match = db.session.get(
        DbNetsessionTourneyMatch, blocking_match_id
    )
    return (
        'Der Sieger lässt sich nicht mehr ändern, weil ein Folge-Match '
        f'(Runde {db_blocking_match.round_no}, Match {db_blocking_match.match_no}) '
        'schon ein Ergebnis hat. Lösche zuerst dieses Ergebnis.'
    )

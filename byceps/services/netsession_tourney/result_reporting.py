"""
byceps.services.netsession_tourney.result_reporting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The steps of reporting a match result, used by `result_service.report_result`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from byceps.database import db
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyResultReportReceipt,
)
from .double_grand_final import (
    is_match_marked_as_skipped_double_grand_final,
)
from .models import (
    MatchID,
    MatchResult,
    MatchState,
    Stage,
    Tournament,
    TournamentMode,
    TournamentStatus,
)
from .result_reporting_sides import (
    advance_after_completion as advance_after_completion,
    load_match_sides as load_match_sides,
    MatchSides as MatchSides,
)
from .result_reporting_store import (
    ResultReport,
    store_reported_result as store_reported_result,
)
from .service_helpers import append_audit_log, db_match_result_to_model


REPORTABLE_MATCH_STATES = {
    MatchState.ready,
    MatchState.in_progress,
    MatchState.pending_confirmation,
}


def find_result_of_repeated_report(
    match_id: MatchID, idempotency_key: str
) -> Result[MatchResult, str] | None:
    """Return the stored result if this report was already processed."""
    db_receipt = db.session.scalar(
        select(DbNetsessionTourneyResultReportReceipt).filter_by(
            match_id=match_id,
            idempotency_key=idempotency_key,
        )
    )
    if db_receipt is None:
        return None

    db_existing_result = db.session.get(
        DbNetsessionTourneyMatchResult, db_receipt.result_id
    )
    if db_existing_result is None:
        return Err('Idempotency receipt references unknown result.')
    return Ok(db_match_result_to_model(db_existing_result))


def validate_report_allowed(
    tournament: Tournament,
    db_match: DbNetsessionTourneyMatch,
    stage: Stage,
    *,
    actor_is_admin_or_referee: bool,
) -> str | None:
    """Return an error message, or `None` if a result may be reported."""
    if not actor_is_admin_or_referee:
        if tournament.status != TournamentStatus.live:
            return (
                'Ergebnisse lassen sich nur melden, während das Turnier läuft.'
            )

        if MatchState(db_match.state) not in REPORTABLE_MATCH_STATES:
            return 'In diesem Match-Status lässt sich kein Ergebnis melden.'

    if is_match_marked_as_skipped_double_grand_final(stage, db_match.id):
        return 'Dieses Match entfällt, weil kein zweites Finale nötig ist.'

    return None


def is_conflicting_duel_report(
    tournament: Tournament,
    db_result: DbNetsessionTourneyMatchResult,
    report: ResultReport,
    reports_agree: bool,
) -> bool:
    return (
        not report.by_admin
        and tournament.mode == TournamentMode.duel
        and db_result.submitted_by_user_id is not None
        and db_result.submitted_by_user_id != report.actor_user_id
        and not reports_agree
    )


def apply_match_state(
    db_match: DbNetsessionTourneyMatch,
    db_result: DbNetsessionTourneyMatchResult,
    new_state: MatchState,
    report: ResultReport,
    now: datetime,
) -> None:
    db_match.state = new_state.value
    db_match.reported_by_user_id = report.actor_user_id
    db_match.updated_at = now
    db_match.lock_version += 1
    if report.by_admin:
        db_match.confirmed_by_admin_id = report.actor_user_id
        db_result.confirmed_by_admin_id = report.actor_user_id
        db_result.confirmation_comment = report.admin_comment

    if not report.by_admin and new_state == MatchState.pending_confirmation:
        db_match.confirmation_deadline_at = now + timedelta(minutes=15)
    else:
        db_match.confirmation_deadline_at = None


def store_receipt_and_audit(
    match_id: MatchID,
    report: ResultReport,
    db_result: DbNetsessionTourneyMatchResult,
    new_state: MatchState,
    now: datetime,
) -> None:
    """Remember the report (against repeats) and write the audit log."""
    db.session.add(
        DbNetsessionTourneyResultReportReceipt(
            generate_uuid7(),
            match_id,
            report.idempotency_key,
            db_result.id,
            now,
        )
    )
    append_audit_log(
        actor_user_id=report.actor_user_id,
        object_type='match',
        object_id=match_id,
        action='result_reported',
        payload={
            'winner_slot': report.winner_slot,
            'score': report.score_data,
            'ranking': report.ranking_data,
            'state': new_state.value,
            'reason_code': report.reason_code,
            'comment': report.admin_comment,
            'correlation_id': report.correlation_id,
        },
        created_at=now,
    )

"""
byceps.services.netsession_tourney.result_reporting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The steps of reporting a match result, used by `result_service.report_result`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from byceps.database import db
from byceps.services.user.models import UserID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyResultReportReceipt,
)
from .double_grand_final import (
    is_match_marked_as_skipped_double_grand_final,
    update_optional_double_grand_final_state,
)
from .engines.registry import find_stage_engine
from .match_advancement import advance_stage_from_match, auto_advance_byes
from .models import (
    MatchID,
    MatchResult,
    MatchResultID,
    MatchState,
    Stage,
    Tournament,
    TournamentID,
    TournamentMode,
    TournamentStatus,
)
from .result_deletion import find_match_result_delete_blocker
from .service_helpers import append_audit_log, db_match_result_to_model
from .swiss_correction import prepare_swiss_winner_change
from .tournament_queries import ACTIVE_PARTICIPANT_STATUS_VALUES


REPORTABLE_MATCH_STATES = {
    MatchState.ready,
    MatchState.in_progress,
    MatchState.pending_confirmation,
}


@dataclass(frozen=True, kw_only=True)
class MatchSides:
    """The slots of a match and the active participants in them."""

    db_slots: list[DbNetsessionTourneyMatchSlot]
    db_participants_by_id: dict[Any, DbNetsessionTourneyParticipant]

    def manager_user_ids(self) -> set[UserID]:
        return {
            participant.manager_user_id
            for participant in self.db_participants_by_id.values()
            if participant.manager_user_id is not None
        }

    def slot_no_managed_by(self, user_id: UserID) -> int | None:
        for db_slot in self.db_slots:
            db_participant = (
                self.db_participants_by_id.get(db_slot.participant_id)
                if db_slot.participant_id is not None
                else None
            )
            if (
                db_participant is not None
                and db_participant.manager_user_id == user_id
            ):
                return db_slot.slot_no
        return None

    def participant_id_in_slot(self, slot_no: int | None):
        for db_slot in self.db_slots:
            if db_slot.slot_no == slot_no:
                return db_slot.participant_id
        return None


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


def load_match_sides(match_id: MatchID) -> MatchSides:
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=match_id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()
    participant_ids = {
        slot.participant_id for slot in db_slots if slot.participant_id
    }
    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter(DbNetsessionTourneyParticipant.id.in_(participant_ids))
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    ).all()
    return MatchSides(
        db_slots=list(db_slots),
        db_participants_by_id={p.id: p for p in db_participants},
    )


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
        return Ok((db_result, False))

    reports_agree = (
        db_result.winner_slot == report.winner_slot
        and db_result.score_json == report.score_data
        and db_result.ranking_json == report.ranking_data
        and db_result.submitted_by_user_id != report.actor_user_id
    )
    if (
        report.by_admin
        and db_result.submitted_by_user_id is not None
        and not report.admin_comment
    ):
        return Err('Korrekturen durch Admins brauchen einen Kommentar.')

    winner_change_error = _check_winner_change_allowed(
        match_id, db_result, report
    )
    if winner_change_error is not None:
        return Err(winner_change_error)

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

    return Ok((db_result, reports_agree))


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


def advance_after_completion(
    tournament_id: TournamentID,
    stage: Stage,
    match_id: MatchID,
    sides: MatchSides,
    winner_slot: int | None,
) -> None:
    """Move winner (and loser) on, let byes advance, handle the reset final."""
    engine = find_stage_engine(stage.type)
    advance_stage_from_match(
        tournament_id=tournament_id,
        stage=stage,
        source_match_id=match_id,
        winner_participant_id=sides.participant_id_in_slot(winner_slot),
        engine=engine,
    )
    if engine is not None:
        auto_advance_byes(tournament_id, stage, engine=engine)
    update_optional_double_grand_final_state(
        stage=stage, source_match_id=match_id
    )


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

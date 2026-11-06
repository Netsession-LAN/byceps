"""
byceps.services.netsession_tourney.result_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Reporting match results (by players or admins) and walkovers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
import structlog

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User, UserID
from byceps.util.result import Err, Ok, Result

from . import domain_service
from .builder_auto_generation import (
    auto_generate_builder_main_stages_from_completed_source,
)
from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyStage,
)
from .discord_payloads import (
    build_discord_match_completed_payload,
)
from .discord_service import (
    enqueue_discord_event,
)
from .models import (
    MatchID,
    MatchResult,
    MatchState,
    TournamentID,
)
from .notification_service import (
    append_notification_for_match_report,
)
from .result_report_mode import (
    determine_post_report_state as _determine_post_report_state,
    get_stage_result_report_mode as _get_stage_result_report_mode,
    validate_actor_matches_report_mode as _validate_actor_matches_report_mode,
)
from .result_reporting import (
    MatchSides,
    ResultReport,
    advance_after_completion,
    apply_match_state,
    find_result_of_repeated_report,
    is_conflicting_duel_report,
    load_match_sides,
    store_receipt_and_audit,
    store_reported_result,
    validate_report_allowed,
)
from .service_helpers import (
    db_match_result_to_model,
    db_stage_to_model,
    db_tournament_to_model,
)
from .tournament_queries import (
    find_db_tournament_for_party,
)


log = structlog.get_logger()


def report_result(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    actor_user_id: UserID,
    *,
    idempotency_key: str,
    winner_slot: int | None,
    score: dict[str, Any] | None = None,
    ranking: dict[str, Any] | None = None,
    actor_is_admin_or_referee: bool = False,
    admin_comment: str | None = None,
    reason_code: str | None = None,
    correlation_id: str | None = None,
) -> Result[MatchResult, str]:
    report = ResultReport(
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        winner_slot=winner_slot,
        score_data=score or {},
        ranking_data=ranking or {},
        by_admin=actor_is_admin_or_referee,
        admin_comment=admin_comment,
        reason_code=reason_code,
        correlation_id=correlation_id,
    )

    db_tournament = find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch)
        .filter_by(id=match_id, tournament_id=tournament_id)
        .with_for_update()
    )
    if db_match is None:
        return Err('Unbekanntes Match.')

    repeated = find_result_of_repeated_report(match_id, idempotency_key)
    if repeated is not None:
        return repeated

    db_stage = db.session.get(DbNetsessionTourneyStage, db_match.stage_id)
    if db_stage is None:
        return Err('Unbekannte Stage.')
    stage = db_stage_to_model(db_stage)
    tournament = db_tournament_to_model(db_tournament)

    not_allowed = validate_report_allowed(
        tournament, db_match, stage, actor_is_admin_or_referee=report.by_admin
    )
    if not_allowed:
        return Err(not_allowed)

    sides = load_match_sides(match_id)
    if not domain_service.can_actor_report_match_result(
        tournament.mode, report.by_admin, actor_user_id in sides.manager_user_ids()
    ):
        return Err('Du darfst für dieses Match kein Ergebnis melden.')

    report_mode = _get_stage_result_report_mode(stage.settings)
    report_mode_error = _validate_actor_matches_report_mode(
        tournament.mode,
        report_mode,
        actor_is_admin_or_referee=report.by_admin,
        actor_slot_no=sides.slot_no_managed_by(actor_user_id),
        winner_slot=winner_slot,
    )
    if report_mode_error is not None:
        return Err(report_mode_error)

    return _apply_report(
        db_tournament, tournament, db_match, stage, sides, report, report_mode
    )


def _apply_report(
    db_tournament, tournament, db_match, stage, sides, report, report_mode
) -> Result[MatchResult, str]:
    """Store the (validated) report, update the match and announce it."""
    now = datetime.utcnow()
    store_result = store_reported_result(db_match.id, report, now)
    if store_result.is_err():
        return Err(store_result.unwrap_err())
    db_result, reports_agree = store_result.unwrap()

    new_state = _determine_post_report_state(
        tournament.mode,
        report_mode,
        actor_is_admin_or_referee=report.by_admin,
        reports_agree=reports_agree,
        conflicting_duel_reports=is_conflicting_duel_report(
            tournament, db_result, report, reports_agree
        ),
    )
    apply_match_state(db_match, db_result, new_state, report, now)
    store_receipt_and_audit(db_match.id, report, db_result, new_state, now)

    completed = new_state == MatchState.completed
    if completed:
        advance_after_completion(
            tournament.id, stage, db_match.id, sides, report.winner_slot
        )

    append_notification_for_match_report(db_match, stage, report.actor_user_id)
    if completed:
        _announce_and_continue_after_completion(
            db_tournament, db_match, stage, sides, report
        )
    db.session.commit()

    log.info(
        'netsession_tourney.result_reported',
        tournament_id=str(tournament.id),
        stage_id=str(stage.id),
        match_id=str(db_match.id),
        actor_user_id=str(report.actor_user_id),
        correlation_id=report.correlation_id,
        state=new_state.value,
    )
    return Ok(db_match_result_to_model(db_result))


def _announce_and_continue_after_completion(
    db_tournament, db_match, stage, sides: MatchSides, report: ResultReport
) -> None:
    """Post the result to Discord; generate main stages of the stage builder
    once their preliminaries are complete."""
    enqueue_discord_event(
        db_tournament.party_id,
        db_tournament.id,
        event_name='match_completed',
        payload=build_discord_match_completed_payload(
            db_tournament,
            db_match,
            stage,
            sides.db_slots,
            sides.db_participants_by_id,
            report.winner_slot,
            report.score_data,
            report.ranking_data,
        ),
    )
    auto_generate_builder_main_stages_from_completed_source(
        party_id=db_tournament.party_id,
        tournament_id=db_tournament.id,
        source_stage_id=stage.id,
        actor_user_id=report.actor_user_id,
        correlation_id=report.correlation_id,
    )


def apply_walkover_result(
    party_id: PartyID,
    tournament_id: TournamentID,
    match_id: MatchID,
    initiator: User,
    *,
    winner_slot: int,
    idempotency_key: str,
    comment: str,
    correlation_id: str | None = None,
) -> Result[MatchResult, str]:
    comment = comment.strip()
    if not comment:
        return Err('Bitte einen Kommentar angeben.')

    return report_result(
        party_id,
        tournament_id,
        match_id,
        initiator.id,
        idempotency_key=idempotency_key,
        winner_slot=winner_slot,
        score={'walkover': True},
        ranking={},
        actor_is_admin_or_referee=True,
        admin_comment=comment,
        reason_code='walkover',
        correlation_id=correlation_id,
    )

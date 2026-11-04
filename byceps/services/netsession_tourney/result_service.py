"""
byceps.services.netsession_tourney.result_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Reporting match results (by players or admins) and walkovers.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
import structlog

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User, UserID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from . import domain_service
from .builder_auto_generation import (
    _auto_generate_builder_main_stages_from_completed_source,
)
from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyResultReportReceipt,
    DbNetsessionTourneyStage,
)
from .discord_payloads import (
    _build_discord_match_completed_payload,
)
from .discord_service import (
    enqueue_discord_event,
)
from .double_grand_final import (
    _is_match_marked_as_skipped_double_grand_final,
    _update_optional_double_grand_final_state,
)
from .engines.registry import (
    find_stage_engine,
)
from .match_advancement import (
    _advance_stage_from_match,
    _auto_advance_byes,
)
from .models import (
    MatchID,
    MatchResult,
    MatchResultID,
    MatchState,
    TournamentID,
    TournamentMode,
    TournamentStatus,
)
from .notification_service import (
    _append_notification_for_match_report,
)
from .result_report_mode import (
    determine_post_report_state as _determine_post_report_state,
    get_stage_result_report_mode as _get_stage_result_report_mode,
    validate_actor_matches_report_mode as _validate_actor_matches_report_mode,
)
from .service_helpers import (
    _append_audit_log,
    _db_match_result_to_model,
    _db_stage_to_model,
    _db_tournament_to_model,
)
from .tournament_queries import (
    _find_db_tournament_for_party,
    ACTIVE_PARTICIPANT_STATUS_VALUES,
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
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    db_match = db.session.scalar(
        select(DbNetsessionTourneyMatch)
        .filter_by(id=match_id, tournament_id=tournament_id)
        .with_for_update()
    )
    if db_match is None:
        return Err('Unbekanntes Match.')

    db_receipt = db.session.scalar(
        select(DbNetsessionTourneyResultReportReceipt).filter_by(
            match_id=match_id,
            idempotency_key=idempotency_key,
        )
    )
    if db_receipt is not None:
        db_existing_result = db.session.get(
            DbNetsessionTourneyMatchResult, db_receipt.result_id
        )
        if db_existing_result is None:
            return Err('Idempotency receipt references unknown result.')
        return Ok(_db_match_result_to_model(db_existing_result))

    db_stage = db.session.get(DbNetsessionTourneyStage, db_match.stage_id)
    if db_stage is None:
        return Err('Unbekannte Stage.')
    stage = _db_stage_to_model(db_stage)
    tournament = _db_tournament_to_model(db_tournament)

    if not actor_is_admin_or_referee:
        if tournament.status != TournamentStatus.live:
            return Err(
                'Ergebnisse lassen sich nur melden, während das Turnier läuft.'
            )

        if MatchState(db_match.state) not in {
            MatchState.ready,
            MatchState.in_progress,
            MatchState.pending_confirmation,
        }:
            return Err(
                'In diesem Match-Status lässt sich kein Ergebnis melden.'
            )

    if _is_match_marked_as_skipped_double_grand_final(stage, match_id):
        return Err(
            'Dieses Match entfällt, weil kein zweites Finale nötig ist.'
        )

    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=match_id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()
    participant_ids = {slot.participant_id for slot in db_slots if slot.participant_id}
    db_participants = db.session.scalars(
        select(DbNetsessionTourneyParticipant)
        .filter(DbNetsessionTourneyParticipant.id.in_(participant_ids))
        .filter(
            DbNetsessionTourneyParticipant.status.in_(
                ACTIVE_PARTICIPANT_STATUS_VALUES
            )
        )
    ).all()
    db_participants_by_id = {
        db_participant.id: db_participant for db_participant in db_participants
    }
    manager_user_ids = {
        participant.manager_user_id
        for participant in db_participants
        if participant.manager_user_id is not None
    }
    manager_user_id_by_slot_no = {
        db_slot.slot_no: (
            db_participants_by_id.get(db_slot.participant_id).manager_user_id
            if db_slot.participant_id is not None
            and db_participants_by_id.get(db_slot.participant_id) is not None
            else None
        )
        for db_slot in db_slots
    }
    actor_slot_no = next(
        (
            slot_no
            for slot_no, manager_user_id in manager_user_id_by_slot_no.items()
            if manager_user_id == actor_user_id
        ),
        None,
    )
    is_match_participant_manager = actor_user_id in manager_user_ids
    if not domain_service.can_actor_report_match_result(
        tournament.mode,
        actor_is_admin_or_referee,
        is_match_participant_manager,
    ):
        return Err('Du darfst für dieses Match kein Ergebnis melden.')

    stage_result_report_mode = _get_stage_result_report_mode(stage.settings)
    report_mode_validation_error = _validate_actor_matches_report_mode(
        tournament.mode,
        stage_result_report_mode,
        actor_is_admin_or_referee=actor_is_admin_or_referee,
        actor_slot_no=actor_slot_no,
        winner_slot=winner_slot,
    )
    if report_mode_validation_error is not None:
        return Err(report_mode_validation_error)

    score_data = score or {}
    ranking_data = ranking or {}
    now = datetime.utcnow()

    db_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(match_id=match_id)
    )
    if db_result is None:
        db_result = DbNetsessionTourneyMatchResult(
            MatchResultID(generate_uuid7()),
            match_id,
            now,
            winner_slot=winner_slot,
            score_json=score_data,
            ranking_json=ranking_data,
            submitted_by_user_id=actor_user_id,
        )
        db.session.add(db_result)
        reports_agree = False
    else:
        reports_agree = (
            db_result.winner_slot == winner_slot
            and db_result.score_json == score_data
            and db_result.ranking_json == ranking_data
            and db_result.submitted_by_user_id != actor_user_id
        )
        if (
            actor_is_admin_or_referee
            and db_result.submitted_by_user_id is not None
            and not admin_comment
        ):
            return Err('Admin corrections require a comment.')

        db_result.winner_slot = winner_slot
        db_result.score_json = score_data
        db_result.ranking_json = ranking_data
        db_result.updated_at = now
        if db_result.submitted_by_user_id is None:
            db_result.submitted_by_user_id = actor_user_id
        if (
            not actor_is_admin_or_referee
            and db_result.submitted_by_user_id != actor_user_id
        ):
            db_result.confirmed_by_user_id = actor_user_id

    conflicting_duel_reports = (
        not actor_is_admin_or_referee
        and tournament.mode == TournamentMode.duel
        and db_result.submitted_by_user_id is not None
        and db_result.submitted_by_user_id != actor_user_id
        and not reports_agree
    )

    new_state = _determine_post_report_state(
        tournament.mode,
        stage_result_report_mode,
        actor_is_admin_or_referee=actor_is_admin_or_referee,
        reports_agree=reports_agree,
        conflicting_duel_reports=conflicting_duel_reports,
    )

    db_match.state = new_state.value
    db_match.reported_by_user_id = actor_user_id
    db_match.updated_at = now
    db_match.lock_version += 1
    if actor_is_admin_or_referee:
        db_match.confirmed_by_admin_id = actor_user_id
        db_result.confirmed_by_admin_id = actor_user_id
        db_result.confirmation_comment = admin_comment

    if not actor_is_admin_or_referee and new_state == MatchState.pending_confirmation:
        db_match.confirmation_deadline_at = now + timedelta(minutes=15)
    else:
        db_match.confirmation_deadline_at = None

    db.session.add(
        DbNetsessionTourneyResultReportReceipt(
            generate_uuid7(),
            match_id,
            idempotency_key,
            db_result.id,
            now,
        )
    )

    if new_state == MatchState.completed:
        winner_participant_id = None
        for db_slot in db_slots:
            if db_slot.slot_no == winner_slot:
                winner_participant_id = db_slot.participant_id
                break
        engine = find_stage_engine(stage.type)
        _advance_stage_from_match(
            tournament_id=tournament_id,
            stage=stage,
            source_match_id=match_id,
            winner_participant_id=winner_participant_id,
            engine=engine,
        )
        if engine is not None:
            _auto_advance_byes(tournament_id, stage, engine=engine)
        _update_optional_double_grand_final_state(
            stage=stage, source_match_id=match_id
        )
    _append_audit_log(
        actor_user_id=actor_user_id,
        object_type='match',
        object_id=match_id,
        action='result_reported',
        payload={
            'winner_slot': winner_slot,
            'score': score_data,
            'ranking': ranking_data,
            'state': new_state.value,
            'reason_code': reason_code,
            'comment': admin_comment,
            'correlation_id': correlation_id,
        },
        created_at=now,
    )

    db.session.commit()
    _append_notification_for_match_report(db_match, stage, actor_user_id)
    if new_state == MatchState.completed:
        enqueue_discord_event(
            party_id,
            tournament_id,
            event_name='match_completed',
            payload=_build_discord_match_completed_payload(
                db_tournament,
                db_match,
                stage,
                db_slots,
                db_participants_by_id,
                winner_slot,
                score_data,
                ranking_data,
            ),
        )
    if new_state == MatchState.completed:
        _auto_generate_builder_main_stages_from_completed_source(
            party_id=party_id,
            tournament_id=tournament_id,
            source_stage_id=stage.id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )

    log.info(
        'netsession_tourney.result_reported',
        tournament_id=str(tournament_id),
        stage_id=str(stage.id),
        match_id=str(match_id),
        actor_user_id=str(actor_user_id),
        correlation_id=correlation_id,
        state=new_state.value,
    )

    return Ok(_db_match_result_to_model(db_result))


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

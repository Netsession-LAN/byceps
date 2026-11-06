"""
byceps.services.netsession_tourney.match_advancement
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Winners and losers move on to their next matches; byes advance automatically.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from byceps.database import db
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
)
from .double_grand_final import (
    _update_optional_double_grand_final_state,
)
from .engines.base import StageEngine
from .engines.registry import (
    find_stage_engine,
)
from .ffa_qualifiers import (
    _get_ffa_single_elimination_qualifier_ids,
)
from .models import (
    MatchID,
    MatchResultID,
    MatchState,
    ParticipantID,
    SourceOutcome,
    Stage,
    StageType,
    TournamentID,
)
from .notification_service import (
    _enqueue_match_ready_notifications,
)
from .participant_state import (
    _calculate_match_state_for_slots,
    _get_tournament_status_value,
)
from .service_helpers import (
    _append_audit_log,
)
from .swiss_stage import (
    _seed_swiss_follow_up_rounds,
)


def resolve_pending_confirmations() -> int:
    """Send results the opponent did not confirm in time to admin review."""
    now = datetime.utcnow()
    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter(
            DbNetsessionTourneyMatch.state
            == MatchState.pending_confirmation.value
        )
        .filter(DbNetsessionTourneyMatch.confirmation_deadline_at < now)
    ).all()

    for db_match in db_matches:
        db_match.state = MatchState.needs_admin_review.value
        db_match.updated_at = now
        db_match.confirmation_deadline_at = None
        _append_audit_log(
            actor_user_id=None,
            object_type='match',
            object_id=db_match.id,
            action='result_confirmation_timed_out',
            payload={'reason_code': 'confirmation_timeout'},
            created_at=now,
        )

    db.session.commit()
    return len(db_matches)


def _auto_advance_byes(
    tournament_id: TournamentID, stage: Stage, *, engine: StageEngine
) -> None:
    while True:
        progressed = False
        db_matches = db.session.scalars(
            select(DbNetsessionTourneyMatch)
            .filter_by(tournament_id=tournament_id, stage_id=stage.id)
            .filter(
                DbNetsessionTourneyMatch.state.in_(
                    [MatchState.pending.value, MatchState.ready.value]
                )
            )
            .order_by(
                DbNetsessionTourneyMatch.round_no.asc(),
                DbNetsessionTourneyMatch.match_no.asc(),
            )
        ).all()
        for db_match in db_matches:
            if _auto_advance_bye_match(
                tournament_id, stage, db_match, engine=engine
            ):
                progressed = True
        db.session.flush()
        if not progressed:
            return


def _auto_advance_bye_match(
    tournament_id: TournamentID,
    stage: Stage,
    db_match: DbNetsessionTourneyMatch,
    *,
    engine: StageEngine,
) -> bool:
    """Complete the match as walkover if it is a bye; return whether it was."""
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=db_match.id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()
    filled_slots = [slot for slot in db_slots if slot.participant_id]
    has_any_source_slots = any(
        slot.source_match_slot_id is not None for slot in db_slots
    )
    # Auto-advance only hard byes, not unresolved feeder slots.
    # A feeder slot with no participant is considered resolved if the
    # source match is already completed and produced no winner/loser
    # for that outcome path (e.g. loser path from a bye match).
    unresolved_source_slots = [
        slot for slot in db_slots if _is_unresolved_source_slot(slot)
    ]
    if unresolved_source_slots:
        return False

    winner_slot_no: int | None = None
    winner_participant_id: ParticipantID | None = None

    if len(filled_slots) == 1:
        winner_slot_no = filled_slots[0].slot_no
        winner_participant_id = filled_slots[0].participant_id
    elif len(filled_slots) == 0:
        # Propagate an explicitly empty feeder path (e.g. LB branch fed
        # only by bye matches), but never consume pre-created placeholder
        # matches that do not have resolved feeder sources yet.
        if not has_any_source_slots:
            return False
        winner_slot_no = None
        winner_participant_id = None
    else:
        return False

    db_result = DbNetsessionTourneyMatchResult(
        MatchResultID(generate_uuid7()),
        db_match.id,
        datetime.utcnow(),
        winner_slot=winner_slot_no,
        score_json={
            'walkover': True,
            'empty_match': len(filled_slots) == 0,
        },
        ranking_json={},
        submitted_by_user_id=None,
    )
    db.session.add(db_result)
    db_match.state = MatchState.completed.value
    db_match.updated_at = datetime.utcnow()

    _advance_stage_from_match(
        tournament_id=tournament_id,
        stage=stage,
        source_match_id=db_match.id,
        winner_participant_id=winner_participant_id,
        engine=engine,
    )
    _update_optional_double_grand_final_state(
        stage=stage, source_match_id=db_match.id
    )
    return True


def _is_unresolved_source_slot(slot: DbNetsessionTourneyMatchSlot) -> bool:
    """Tell whether the slot is an empty feeder slot whose source match is
    missing or not completed yet."""
    return (
        slot.participant_id is None
        and slot.source_match_slot_id is not None
        and (
            (
                source_slot := db.session.get(
                    DbNetsessionTourneyMatchSlot,
                    slot.source_match_slot_id,
                )
            )
            is None
            or (
                source_match := db.session.get(
                    DbNetsessionTourneyMatch, source_slot.match_id
                )
            )
            is None
            or source_match.state != MatchState.completed.value
        )
    )


def _advance_stage_from_match(
    *,
    tournament_id: TournamentID,
    stage: Stage,
    source_match_id: MatchID,
    winner_participant_id: ParticipantID | None,
    engine: StageEngine | None = None,
) -> None:
    if engine is None:
        engine = find_stage_engine(stage.type)
    if engine is None:
        return

    if stage.type == StageType.swiss:
        _advance_swiss_stage(tournament_id, stage)
        return

    source_slot = db.session.scalar(
        select(DbNetsessionTourneyMatchSlot).filter_by(
            match_id=source_match_id, slot_no=1
        )
    )
    if source_slot is None:
        return

    source_match_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=source_match_id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()
    loser_participant_id = _find_loser_participant_id(
        source_match_slots, winner_participant_id
    )

    downstream_db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot).filter_by(
            source_match_slot_id=source_slot.id
        )
    ).all()
    downstream_winner_slots = [
        (db_slot.match_id, db_slot.slot_no)
        for db_slot in downstream_db_slots
        if db_slot.source_outcome != SourceOutcome.loser.value
    ]
    downstream_loser_slots = [
        (db_slot.match_id, db_slot.slot_no)
        for db_slot in downstream_db_slots
        if db_slot.source_outcome == SourceOutcome.loser.value
    ]

    if stage.type in {
        StageType.ffa_single_elimination,
        StageType.ffa_flatout2_single_elimination,
    }:
        updates = _build_ffa_qualifier_updates(
            source_match_id, source_match_slots, downstream_winner_slots
        )
    else:
        updates = engine.advance(
            stage, winner_participant_id, downstream_winner_slots
        )
    updates.extend(
        (
            match_id,
            slot_no,
            loser_participant_id,
        )
        for match_id, slot_no in downstream_loser_slots
    )
    ready_match_ids = _apply_downstream_slot_updates(tournament_id, updates)
    db.session.flush()

    _enqueue_notifications_for_still_ready_matches(ready_match_ids)


def _enqueue_notifications_for_still_ready_matches(
    ready_match_ids: set[MatchID],
) -> None:
    for match_id in ready_match_ids:
        db_match = db.session.get(DbNetsessionTourneyMatch, match_id)
        if db_match is None or db_match.state != MatchState.ready.value:
            continue

        _enqueue_match_ready_notifications(db_match)


def _advance_swiss_stage(tournament_id: TournamentID, stage: Stage) -> None:
    ready_match_ids = _seed_swiss_follow_up_rounds(
        tournament_id=tournament_id,
        stage=stage,
    ) or []
    for match_id in ready_match_ids:
        db_match = db.session.get(DbNetsessionTourneyMatch, match_id)
        if db_match is None:
            continue
        _enqueue_match_ready_notifications(db_match)


def _find_loser_participant_id(
    source_match_slots: list[DbNetsessionTourneyMatchSlot],
    winner_participant_id: ParticipantID | None,
) -> ParticipantID | None:
    source_participant_ids = [
        slot.participant_id
        for slot in source_match_slots
        if slot.participant_id is not None
    ]
    loser_participant_id: ParticipantID | None = None
    if winner_participant_id is not None:
        for participant_id in source_participant_ids:
            if participant_id != winner_participant_id:
                loser_participant_id = participant_id
                break
    return loser_participant_id


def _build_ffa_qualifier_updates(
    source_match_id: MatchID,
    source_match_slots: list[DbNetsessionTourneyMatchSlot],
    downstream_winner_slots: list[tuple[MatchID, int]],
) -> list[tuple[MatchID, int, ParticipantID | None]]:
    ranked_participant_ids = _get_ffa_single_elimination_qualifier_ids(
        source_match_id,
        source_match_slots,
        len(downstream_winner_slots),
    )
    return [
        (
            match_id,
            slot_no,
            ranked_participant_ids[index]
            if index < len(ranked_participant_ids)
            else None,
        )
        for index, (match_id, slot_no) in enumerate(
            sorted(downstream_winner_slots, key=lambda item: (item[0], item[1]))
        )
    ]


def _apply_downstream_slot_updates(
    tournament_id: TournamentID,
    updates: list[tuple[MatchID, int, ParticipantID | None]],
) -> set[MatchID]:
    """Put participants into downstream slots and recalculate the states of
    the affected matches; return the IDs of matches that became ready."""
    ready_match_ids: set[MatchID] = set()
    for match_id, slot_no, participant_id in updates:
        db_slot = db.session.scalar(
            select(DbNetsessionTourneyMatchSlot).filter_by(
                match_id=match_id,
                slot_no=slot_no,
            )
        )
        if db_slot is None:
            continue
        db_slot.participant_id = participant_id

        db_match = db.session.get(DbNetsessionTourneyMatch, match_id)
        if db_match is None:
            continue
        previous_state = MatchState(db_match.state)
        db_match_slots = db.session.scalars(
            select(DbNetsessionTourneyMatchSlot).filter_by(match_id=match_id)
        ).all()
        next_state = _calculate_match_state_for_slots(
            tournament_status=_get_tournament_status_value(tournament_id),
            db_match_slots=db_match_slots,
        )
        db_match.state = next_state.value
        db_match.updated_at = datetime.utcnow()
        if previous_state != MatchState.ready and next_state == MatchState.ready:
            ready_match_ids.add(match_id)
    return ready_match_ids

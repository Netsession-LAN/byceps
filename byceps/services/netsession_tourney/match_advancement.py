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
    update_optional_double_grand_final_state,
)
from .engines.base import StageEngine
from .engines.registry import (
    find_stage_engine,
)
from .match_advancement_byes import (
    _Bye,
    _find_bye,
)
from .match_advancement_slots import (
    _apply_downstream_slot_updates,
    _build_winner_slot_updates,
    _find_loser_participant_id,
    _split_downstream_slots,
)
from .models import (
    MatchID,
    MatchResultID,
    MatchState,
    ParticipantID,
    Stage,
    StageType,
    TournamentID,
)
from .notification_service import (
    enqueue_match_ready_notifications,
)
from .service_helpers import (
    append_audit_log,
)
from .swiss_stage import (
    seed_swiss_follow_up_rounds,
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
        append_audit_log(
            actor_user_id=None,
            object_type='match',
            object_id=db_match.id,
            action='result_confirmation_timed_out',
            payload={'reason_code': 'confirmation_timeout'},
            created_at=now,
        )

    db.session.commit()
    return len(db_matches)


def auto_advance_byes(
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

    bye = _find_bye(db_slots)
    if bye is None:
        return False

    _complete_bye_match(tournament_id, stage, db_match, bye, engine=engine)
    return True


def _complete_bye_match(
    tournament_id: TournamentID,
    stage: Stage,
    db_match: DbNetsessionTourneyMatch,
    bye: _Bye,
    *,
    engine: StageEngine,
) -> None:
    winner_slot_no, winner_participant_id, is_empty_match = bye

    db_result = DbNetsessionTourneyMatchResult(
        MatchResultID(generate_uuid7()),
        db_match.id,
        datetime.utcnow(),
        winner_slot=winner_slot_no,
        score_json={
            'walkover': True,
            'empty_match': is_empty_match,
        },
        ranking_json={},
        submitted_by_user_id=None,
    )
    db.session.add(db_result)
    db_match.state = MatchState.completed.value
    db_match.updated_at = datetime.utcnow()

    advance_stage_from_match(
        tournament_id=tournament_id,
        stage=stage,
        source_match_id=db_match.id,
        winner_participant_id=winner_participant_id,
        engine=engine,
    )
    update_optional_double_grand_final_state(
        stage=stage, source_match_id=db_match.id
    )


def advance_stage_from_match(
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

    _advance_from_source_slot(
        tournament_id=tournament_id,
        stage=stage,
        source_match_id=source_match_id,
        source_slot=source_slot,
        winner_participant_id=winner_participant_id,
        engine=engine,
    )


def _advance_from_source_slot(
    *,
    tournament_id: TournamentID,
    stage: Stage,
    source_match_id: MatchID,
    source_slot: DbNetsessionTourneyMatchSlot,
    winner_participant_id: ParticipantID | None,
    engine: StageEngine,
) -> None:
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
    downstream_winner_slots, downstream_loser_slots = _split_downstream_slots(
        downstream_db_slots
    )

    updates = _build_winner_slot_updates(
        stage,
        engine,
        source_match_id=source_match_id,
        source_match_slots=source_match_slots,
        winner_participant_id=winner_participant_id,
        downstream_winner_slots=downstream_winner_slots,
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

        enqueue_match_ready_notifications(db_match)


def _advance_swiss_stage(tournament_id: TournamentID, stage: Stage) -> None:
    ready_match_ids = (
        seed_swiss_follow_up_rounds(
            tournament_id=tournament_id,
            stage=stage,
        )
        or []
    )
    for match_id in ready_match_ids:
        db_match = db.session.get(DbNetsessionTourneyMatch, match_id)
        if db_match is None:
            continue
        enqueue_match_ready_notifications(db_match)

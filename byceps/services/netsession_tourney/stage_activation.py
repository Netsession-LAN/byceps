"""
byceps.services.netsession_tourney.stage_activation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stages and matches when a tournament goes live or back to draft, and their deletion.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import delete, select

from byceps.database import db

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchChatMessage,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyResultReportReceipt,
    DbNetsessionTourneyStage,
)
from .models import (
    MatchID,
    MatchState,
    Stage,
    StageID,
    StageStatus,
    TournamentID,
    TournamentStatus,
)
from .participant_state import (
    calculate_match_state_for_slots,
    get_participant_status_value_by_participant_id_for_slots,
)


def delete_stage_matches(stage_id: StageID) -> None:
    db_match_ids = db.session.scalars(
        select(DbNetsessionTourneyMatch.id).filter_by(stage_id=stage_id)
    ).all()
    if not db_match_ids:
        return

    db.session.execute(
        delete(DbNetsessionTourneyMatchChatMessage).filter(
            DbNetsessionTourneyMatchChatMessage.match_id.in_(db_match_ids)
        )
    )
    db.session.execute(
        delete(DbNetsessionTourneyResultReportReceipt).filter(
            DbNetsessionTourneyResultReportReceipt.match_id.in_(db_match_ids)
        )
    )
    db.session.execute(
        delete(DbNetsessionTourneyMatchResult).filter(
            DbNetsessionTourneyMatchResult.match_id.in_(db_match_ids)
        )
    )
    db.session.execute(
        delete(DbNetsessionTourneyMatchSlot).filter(
            DbNetsessionTourneyMatchSlot.match_id.in_(db_match_ids)
        )
    )
    db.session.execute(delete(DbNetsessionTourneyMatch).filter_by(stage_id=stage_id))


def delete_all_stages_for_tournament(tournament_id: TournamentID) -> int:
    stage_ids = db.session.scalars(
        select(DbNetsessionTourneyStage.id).filter_by(tournament_id=tournament_id)
    ).all()
    for stage_id in stage_ids:
        delete_stage_matches(stage_id)

    db.session.execute(
        delete(DbNetsessionTourneyStage).filter_by(tournament_id=tournament_id)
    )
    return len(stage_ids)


def activate_prepared_stages_for_live_tournament(
    tournament_id: TournamentID, stages: list[Stage]
) -> StageID | None:
    stage_ids_with_matches = set(
        db.session.scalars(
            select(DbNetsessionTourneyMatch.stage_id)
            .filter_by(tournament_id=tournament_id)
            .distinct()
        ).all()
    )
    if not stage_ids_with_matches:
        return None

    db_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ).all()
    db_stage_by_id = {db_stage.id: db_stage for db_stage in db_stages}

    first_live_stage_id = None
    for stage in stages:
        if stage.id not in stage_ids_with_matches:
            continue

        db_stage = db_stage_by_id.get(stage.id)
        if db_stage is None:
            continue

        if db_stage.status == StageStatus.draft.value:
            db_stage.status = StageStatus.live.value
            db_stage.updated_at = datetime.utcnow()

        if first_live_stage_id is None:
            first_live_stage_id = stage.id

    return first_live_stage_id


def activate_prepared_matches_for_live_tournament(
    tournament_id: TournamentID,
) -> list[DbNetsessionTourneyMatch]:
    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(tournament_id=tournament_id)
        .order_by(
            DbNetsessionTourneyMatch.stage_id.asc(),
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()
    if not db_matches:
        return []

    match_ids = [db_match.id for db_match in db_matches]
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter(DbNetsessionTourneyMatchSlot.match_id.in_(match_ids))
        .order_by(
            DbNetsessionTourneyMatchSlot.match_id.asc(),
            DbNetsessionTourneyMatchSlot.slot_no.asc(),
        )
    ).all()
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = (
        defaultdict(list)
    )
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)

    participant_status_value_by_participant_id = (
        get_participant_status_value_by_participant_id_for_slots(db_slots)
    )

    ready_matches: list[DbNetsessionTourneyMatch] = []
    for db_match in db_matches:
        if db_match.state == MatchState.completed.value:
            continue

        next_state = calculate_match_state_for_slots(
            tournament_status=TournamentStatus.live.value,
            db_match_slots=slots_by_match_id.get(db_match.id, []),
            participant_status_value_by_participant_id=participant_status_value_by_participant_id,
        )
        db_match.state = next_state.value
        db_match.updated_at = datetime.utcnow()
        if next_state == MatchState.ready:
            ready_matches.append(db_match)

    return ready_matches


def demote_prepared_matches_for_draft_tournament(
    tournament_id: TournamentID,
) -> None:
    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch).filter_by(tournament_id=tournament_id)
    ).all()
    if not db_matches:
        return

    match_ids = [db_match.id for db_match in db_matches]
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter(DbNetsessionTourneyMatchSlot.match_id.in_(match_ids))
        .order_by(
            DbNetsessionTourneyMatchSlot.match_id.asc(),
            DbNetsessionTourneyMatchSlot.slot_no.asc(),
        )
    ).all()
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]] = (
        defaultdict(list)
    )
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)

    participant_status_value_by_participant_id = (
        get_participant_status_value_by_participant_id_for_slots(db_slots)
    )

    for db_match in db_matches:
        if db_match.state == MatchState.completed.value:
            continue

        db_match.state = calculate_match_state_for_slots(
            tournament_status=TournamentStatus.draft.value,
            db_match_slots=slots_by_match_id.get(db_match.id, []),
            participant_status_value_by_participant_id=participant_status_value_by_participant_id,
        ).value
        db_match.updated_at = datetime.utcnow()

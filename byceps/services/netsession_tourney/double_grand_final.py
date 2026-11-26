"""
byceps.services.netsession_tourney.double_grand_final
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Results and the optional second grand final (bracket reset) of double elimination.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select

from byceps.database import db
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
)
from .models import (
    MatchID,
    MatchResult,
    MatchResultID,
    MatchState,
    SourceOutcome,
    Stage,
    StageType,
)
from .participant_state import (
    calculate_match_state_for_slots,
    get_tournament_status_value,
)
from .service_helpers import (
    db_match_result_to_model,
)


DOUBLE_GRAND_FINAL_SKIPPED_SCORE_FLAG = 'grand_final_reset_skipped'


def is_loser_source_outcome(outcome: SourceOutcome | str | None) -> bool:
    value = getattr(outcome, 'value', outcome)
    return value == 'loser'


def get_match_result_for_match(match_id: MatchID) -> MatchResult | None:
    db_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(match_id=match_id)
    )
    if db_result is None:
        return None

    return db_match_result_to_model(db_result)


def get_match_results(match_ids: set[MatchID]) -> dict[MatchID, MatchResult]:
    if not match_ids:
        return {}

    db_results = db.session.scalars(
        select(DbNetsessionTourneyMatchResult).filter(
            DbNetsessionTourneyMatchResult.match_id.in_(match_ids)
        )
    ).all()
    return {
        item.match_id: db_match_result_to_model(item) for item in db_results
    }


def _is_grand_final_reset_skipped_score(
    score_json: dict[str, Any] | None,
) -> bool:
    if not isinstance(score_json, dict):
        return False

    return bool(score_json.get(DOUBLE_GRAND_FINAL_SKIPPED_SCORE_FLAG))


def is_match_marked_as_skipped_double_grand_final(
    stage: Stage, match_id: MatchID
) -> bool:
    if stage.type != StageType.double_elimination_double_grand_final:
        return False

    db_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(match_id=match_id)
    )
    if db_result is None:
        return False

    return _is_grand_final_reset_skipped_score(db_result.score_json)


def update_optional_double_grand_final_state(
    *, stage: Stage, source_match_id: MatchID
) -> None:
    if stage.type != StageType.double_elimination_double_grand_final:
        return

    reset_match_id = _find_reset_match_id(source_match_id)
    if reset_match_id is None:
        return

    db_source_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(
            match_id=source_match_id
        )
    )
    if db_source_result is None or db_source_result.winner_slot is None:
        return

    db_reset_match = db.session.get(DbNetsessionTourneyMatch, reset_match_id)
    if db_reset_match is None:
        return

    db_reset_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(
            match_id=reset_match_id
        )
    )
    now = datetime.utcnow()

    should_skip_reset_match = db_source_result.winner_slot == 1
    if should_skip_reset_match:
        _mark_reset_match_as_skipped(
            db_reset_match, db_reset_result, reset_match_id, now
        )
        return

    _reopen_reset_match(db_reset_match, db_reset_result, reset_match_id, now)


def _find_reset_match_id(source_match_id: MatchID) -> MatchID | None:
    """Find the bracket reset match fed by both outcomes of the source match
    (grand final 1)."""
    db_source_slot = db.session.scalar(
        select(DbNetsessionTourneyMatchSlot).filter_by(
            match_id=source_match_id, slot_no=1
        )
    )
    if db_source_slot is None or db_source_slot.source_match_slot_id is None:
        return None  # first-round match, not grand final 1 (2 participants)

    downstream_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot).filter_by(
            source_match_slot_id=db_source_slot.id
        )
    ).all()
    if not downstream_slots:
        return None

    downstream_slots_by_match_id = defaultdict(list)
    for db_slot in downstream_slots:
        downstream_slots_by_match_id[db_slot.match_id].append(db_slot)

    reset_match_id = None
    for match_id, slots in downstream_slots_by_match_id.items():
        outcomes = {slot.source_outcome for slot in slots}
        if outcomes == {SourceOutcome.winner.value, SourceOutcome.loser.value}:
            reset_match_id = match_id
            break

    return reset_match_id


def _mark_reset_match_as_skipped(
    db_reset_match: DbNetsessionTourneyMatch,
    db_reset_result: DbNetsessionTourneyMatchResult | None,
    reset_match_id: MatchID,
    now: datetime,
) -> None:
    if db_reset_result is not None and not _is_grand_final_reset_skipped_score(
        db_reset_result.score_json
    ):
        return

    if db_reset_result is None:
        db_reset_result = DbNetsessionTourneyMatchResult(
            MatchResultID(generate_uuid7()),
            reset_match_id,
            now,
            winner_slot=None,
            score_json={
                'display': '-',
                DOUBLE_GRAND_FINAL_SKIPPED_SCORE_FLAG: True,
            },
            ranking_json={},
            submitted_by_user_id=None,
        )
        db.session.add(db_reset_result)
    else:
        db_reset_result.winner_slot = None
        db_reset_result.score_json = {
            **(db_reset_result.score_json or {}),
            DOUBLE_GRAND_FINAL_SKIPPED_SCORE_FLAG: True,
        }
        db_reset_result.updated_at = now

    db_reset_match.state = MatchState.completed.value
    db_reset_match.updated_at = now


def _reopen_reset_match(
    db_reset_match: DbNetsessionTourneyMatch,
    db_reset_result: DbNetsessionTourneyMatchResult | None,
    reset_match_id: MatchID,
    now: datetime,
) -> None:
    if db_reset_result and _is_grand_final_reset_skipped_score(
        db_reset_result.score_json
    ):
        db.session.delete(db_reset_result)

    db_reset_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=reset_match_id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()
    db_reset_match.state = calculate_match_state_for_slots(
        tournament_status=get_tournament_status_value(
            db_reset_match.tournament_id
        ),
        db_match_slots=db_reset_slots,
    ).value
    db_reset_match.updated_at = now

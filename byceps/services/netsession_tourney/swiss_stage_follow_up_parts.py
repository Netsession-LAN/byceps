"""
byceps.services.netsession_tourney.swiss_stage_follow_up_parts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Parts of seeding the Swiss follow-up rounds: loading the stage's
matches, checking a round and applying the seeded specs.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from byceps.database import db

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
)
from .engines.base import MatchSpec
from .models import (
    MatchID,
    MatchState,
    Participant,
    Stage,
    TournamentID,
)
from .participant_state import (
    calculate_match_state_for_slots,
    get_tournament_status_value,
)
from .service_helpers import (
    db_participant_to_model,
)


@dataclass(frozen=True, kw_only=True)
class _SwissStageMatchData:
    db_matches: list[DbNetsessionTourneyMatch]
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]]
    results_by_match_id: dict[MatchID, DbNetsessionTourneyMatchResult]
    participants: list[Participant]


def _group_swiss_matches_by_round_no(
    db_matches: list[DbNetsessionTourneyMatch],
) -> dict[int, list[DbNetsessionTourneyMatch]]:
    matches_by_round_no: dict[int, list[DbNetsessionTourneyMatch]] = (
        defaultdict(list)
    )
    for db_match in db_matches:
        matches_by_round_no[db_match.round_no].append(db_match)
    return matches_by_round_no


def _is_swiss_round_completed(
    round_matches: list[DbNetsessionTourneyMatch],
) -> bool:
    if not round_matches:
        return False

    return not any(
        match.state != MatchState.completed.value for match in round_matches
    )


def _has_occupied_swiss_slots(
    matches: list[DbNetsessionTourneyMatch],
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]],
) -> bool:
    return any(
        slot.participant_id is not None
        for match in matches
        for slot in slots_by_match_id.get(match.id, [])
    )


def _get_swiss_matches_after_round(
    matches_by_round_no: dict[int, list[DbNetsessionTourneyMatch]],
    round_no: int,
) -> list[DbNetsessionTourneyMatch]:
    return [
        m for r, ms in matches_by_round_no.items() if r > round_no for m in ms
    ]


def _load_swiss_stage_match_data(
    tournament_id: TournamentID,
    stage: Stage,
) -> _SwissStageMatchData | None:
    """Load matches, slots, results and participants of the stage, or
    `None` if there are no matches or no participants.
    """
    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(tournament_id=tournament_id, stage_id=stage.id)
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()
    if not db_matches:
        return None

    match_ids = [match.id for match in db_matches]
    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter(DbNetsessionTourneyMatchSlot.match_id.in_(match_ids))
        .order_by(
            DbNetsessionTourneyMatchSlot.match_id.asc(),
            DbNetsessionTourneyMatchSlot.slot_no.asc(),
        )
    ).all()
    slots_by_match_id = _group_swiss_slots_by_match_id(db_slots)
    results_by_match_id = _load_swiss_results_by_match_id(match_ids)
    participants = _load_swiss_slot_participants(db_slots)
    if not participants:
        return None

    return _SwissStageMatchData(
        db_matches=db_matches,
        slots_by_match_id=slots_by_match_id,
        results_by_match_id=results_by_match_id,
        participants=participants,
    )


def _group_swiss_slots_by_match_id(
    db_slots: Sequence[DbNetsessionTourneyMatchSlot],
) -> dict[MatchID, list[DbNetsessionTourneyMatchSlot]]:
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]]
    slots_by_match_id = defaultdict(list)
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)
    return slots_by_match_id


def _load_swiss_results_by_match_id(
    match_ids: list[MatchID],
) -> dict[MatchID, DbNetsessionTourneyMatchResult]:
    return {
        db_result.match_id: db_result
        for db_result in db.session.scalars(
            select(DbNetsessionTourneyMatchResult).filter(
                DbNetsessionTourneyMatchResult.match_id.in_(match_ids)
            )
        ).all()
    }


def _load_swiss_slot_participants(
    db_slots: Sequence[DbNetsessionTourneyMatchSlot],
) -> list[Participant]:
    participant_ids = {
        db_slot.participant_id
        for db_slot in db_slots
        if db_slot.participant_id is not None
    }
    return [
        db_participant_to_model(db_participant)
        for db_participant in db.session.scalars(
            select(DbNetsessionTourneyParticipant).filter(
                DbNetsessionTourneyParticipant.id.in_(participant_ids)
            )
        ).all()
    ]


def _apply_seeded_swiss_specs(
    tournament_id: TournamentID,
    target_matches: list[DbNetsessionTourneyMatch],
    seeded_specs: list[MatchSpec],
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]],
    newly_ready_match_ids: list[MatchID],
) -> None:
    """Write the seeded participants into the target matches' slots and
    collect matches that became ready in `newly_ready_match_ids`.
    """
    specs_by_match_no = {spec.match_no: spec for spec in seeded_specs}
    for db_match in target_matches:
        spec = specs_by_match_no.get(db_match.match_no)
        if spec is None:
            continue

        _apply_seeded_swiss_spec(
            tournament_id,
            db_match,
            spec,
            slots_by_match_id,
            newly_ready_match_ids,
        )


def _apply_seeded_swiss_spec(
    tournament_id: TournamentID,
    db_match: DbNetsessionTourneyMatch,
    spec: MatchSpec,
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]],
    newly_ready_match_ids: list[MatchID],
) -> None:
    db_match_slots = sorted(
        slots_by_match_id.get(db_match.id, []),
        key=lambda slot: slot.slot_no,
    )
    participant_id_by_slot_no = {
        slot.slot_no: slot.participant_id for slot in spec.slots
    }
    for db_slot in db_match_slots:
        db_slot.participant_id = participant_id_by_slot_no.get(db_slot.slot_no)

    next_state = calculate_match_state_for_slots(
        tournament_status=get_tournament_status_value(tournament_id),
        db_match_slots=db_match_slots,
    )
    db_match.state = next_state.value
    if next_state == MatchState.ready:
        if db_match.id not in newly_ready_match_ids:
            newly_ready_match_ids.append(db_match.id)
    db_match.updated_at = datetime.utcnow()

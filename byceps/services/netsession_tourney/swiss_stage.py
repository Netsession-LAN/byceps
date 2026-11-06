"""
byceps.services.netsession_tourney.swiss_stage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Swiss stages: round layout, generation and seeding of follow-up rounds.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any

from sqlalchemy import select

from byceps.database import db
from byceps.util.result import Ok, Result

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyParticipant,
)
from .engines.base import MatchSpec, SlotSpec, StageEngine
from .models import (
    MatchID,
    MatchState,
    Participant,
    Stage,
    Tournament,
    TournamentID,
)
from .participant_state import (
    calculate_match_state_for_slots,
    get_tournament_status_value,
)
from .service_helpers import (
    db_participant_to_model,
)
from .stage_generation_base import (
    StageGenerationPayload,
)
from .swiss_pairing import (
    build_follow_up_swiss_round_specs,
    build_initial_swiss_round_specs,
)
from .swiss_round_reconcile import reconcile_round_placeholders
from .swiss_thresholds import (
    get_round_count_for_swiss_stage,
    get_swiss_threshold_for_round_count,
)


def build_swiss_stage_generation_payload(
    *,
    tournament: Tournament,
    stage: Stage,
    engine: StageEngine,
    participants: list[Participant],
    tournament_id: TournamentID,
) -> Result[StageGenerationPayload, str]:
    del tournament_id

    round_count = get_round_count_for_swiss_stage(
        stage, participant_count=len(participants)
    )
    match_specs = _build_full_swiss_stage_specs(
        participants,
        round_count=round_count,
    )

    return Ok(
        StageGenerationPayload(
            tournament=tournament,
            stage=stage,
            engine=engine,
            participants=participants,
            match_specs=match_specs,
        )
        )


def build_swiss_round_layout(
    participant_count: int,
    round_count: int,
) -> list[dict[str, Any]]:
    if participant_count < 2 or round_count < 1:
        return []

    threshold = get_swiss_threshold_for_round_count(round_count)
    counts_by_record: dict[tuple[int, int], int] = {(0, 0): participant_count}
    rounds: list[dict[str, Any]] = []

    for round_no in range(1, round_count + 1):
        pools = []
        active_records = sorted(
            counts_by_record.items(),
            key=lambda item: (-item[0][0], item[0][1]),
        )
        for (wins, losses), count in active_records:
            if count < 1:
                continue
            pools.append(
                {
                    'wins': wins,
                    'losses': losses,
                    'participant_count': count,
                    'match_count': math.ceil(count / 2),
                }
            )

        rounds.append({'round_no': round_no, 'pools': pools})

        next_counts: dict[tuple[int, int], int] = defaultdict(int)
        for pool in pools:
            wins = pool['wins']
            losses = pool['losses']
            count = pool['participant_count']
            winner_count = math.ceil(count / 2)
            loser_count = count // 2

            if wins + 1 < threshold:
                next_counts[(wins + 1, losses)] += winner_count
            if losses + 1 < threshold:
                next_counts[(wins, losses + 1)] += loser_count

        counts_by_record = dict(next_counts)

    return rounds


def _build_full_swiss_stage_specs(
    participants: list[Participant],
    *,
    round_count: int,
) -> list[MatchSpec]:
    if len(participants) < 2:
        return []

    layout = build_swiss_round_layout(len(participants), round_count)
    if not layout:
        return []

    first_round_specs = build_initial_swiss_round_specs(participants)
    specs = list(first_round_specs)
    match_no = len(first_round_specs) + 1

    for round_layout in layout[1:]:
        for pool in round_layout['pools']:
            for _ in range(pool['match_count']):
                specs.append(
                    MatchSpec(
                        round_no=round_layout['round_no'],
                        match_no=match_no,
                        state='pending',
                        slots=[
                            SlotSpec(
                                slot_no=1,
                                participant_id=None,
                                source_match_no=None,
                            ),
                            SlotSpec(
                                slot_no=2,
                                participant_id=None,
                                source_match_no=None,
                            ),
                        ],
                    )
                )
                match_no += 1

    return specs


@dataclass(frozen=True, kw_only=True)
class _SwissStageMatchData:
    db_matches: list[DbNetsessionTourneyMatch]
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]]
    results_by_match_id: dict[MatchID, DbNetsessionTourneyMatchResult]
    participants: list[Participant]


def seed_swiss_follow_up_rounds(
    *,
    tournament_id: TournamentID,
    stage: Stage,
) -> list[MatchID]:
    newly_ready_match_ids: list[MatchID] = []
    match_data = _load_swiss_stage_match_data(tournament_id, stage)
    if match_data is None:
        return []

    db_matches = match_data.db_matches
    slots_by_match_id = match_data.slots_by_match_id
    participants = match_data.participants

    round_count = get_round_count_for_swiss_stage(
        stage, participant_count=len(participants)
    )
    layout = build_swiss_round_layout(len(participants), round_count)
    matches_by_round_no: dict[int, list[DbNetsessionTourneyMatch]] = defaultdict(list)
    for db_match in db_matches:
        matches_by_round_no[db_match.round_no].append(db_match)

    for round_layout in layout[1:]:
        round_no = round_layout['round_no']
        previous_round_matches = matches_by_round_no.get(round_no - 1, [])
        if not previous_round_matches or any(
            match.state != MatchState.completed.value
            for match in previous_round_matches
        ):
            return []

        target_matches = sorted(
            matches_by_round_no.get(round_no, []),
            key=lambda match: match.match_no,
        )
        if not target_matches:
            return []

        if any(
            slot.participant_id is not None
            for match in target_matches
            for slot in slots_by_match_id.get(match.id, [])
        ):
            continue

        seeded_specs = build_follow_up_swiss_round_specs(
            participants=participants,
            db_matches=db_matches,
            slots_by_match_id=slots_by_match_id,
            results_by_match_id=match_data.results_by_match_id,
            next_round_no=round_no,
            first_match_no=target_matches[0].match_no,
            round_count=round_count,
        )
        if not seeded_specs:
            continue

        target_matches = reconcile_round_placeholders(
            target_matches,
            [m for r, ms in matches_by_round_no.items() if r > round_no for m in ms],
            seeded_specs,
            slots_by_match_id,
        )
        matches_by_round_no[round_no] = target_matches
        _apply_seeded_swiss_specs(
            tournament_id,
            target_matches,
            seeded_specs,
            slots_by_match_id,
            newly_ready_match_ids,
        )

    return newly_ready_match_ids


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
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]]
    slots_by_match_id = defaultdict(list)
    for db_slot in db_slots:
        slots_by_match_id[db_slot.match_id].append(db_slot)

    results_by_match_id = {
        db_result.match_id: db_result
        for db_result in db.session.scalars(
            select(DbNetsessionTourneyMatchResult).filter(
                DbNetsessionTourneyMatchResult.match_id.in_(match_ids)
            )
        ).all()
    }

    participant_ids = {
        db_slot.participant_id
        for db_slot in db_slots
        if db_slot.participant_id is not None
    }
    participants = [
        db_participant_to_model(db_participant)
        for db_participant in db.session.scalars(
            select(DbNetsessionTourneyParticipant).filter(
                DbNetsessionTourneyParticipant.id.in_(participant_ids)
            )
        ).all()
    ]
    if not participants:
        return None

    return _SwissStageMatchData(
        db_matches=db_matches,
        slots_by_match_id=slots_by_match_id,
        results_by_match_id=results_by_match_id,
        participants=participants,
    )


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
    specs_by_match_no = {
        spec.match_no: spec
        for spec in seeded_specs
    }
    for db_match in target_matches:
        spec = specs_by_match_no.get(db_match.match_no)
        if spec is None:
            continue

        db_match_slots = sorted(
            slots_by_match_id.get(db_match.id, []),
            key=lambda slot: slot.slot_no,
        )
        participant_id_by_slot_no = {
            slot.slot_no: slot.participant_id for slot in spec.slots
        }
        for db_slot in db_match_slots:
            db_slot.participant_id = participant_id_by_slot_no.get(
                db_slot.slot_no
            )

        next_state = calculate_match_state_for_slots(
            tournament_status=get_tournament_status_value(tournament_id),
            db_match_slots=db_match_slots,
        )
        db_match.state = next_state.value
        if next_state == MatchState.ready:
            if db_match.id not in newly_ready_match_ids:
                newly_ready_match_ids.append(db_match.id)
        db_match.updated_at = datetime.utcnow()

"""
byceps.services.netsession_tourney.swiss_stage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Swiss stages: round layout, generation and seeding of follow-up rounds.
"""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Any

from byceps.util.result import Ok, Result

from .dbmodels import (
    DbNetsessionTourneyMatch,
)
from .engines.base import MatchSpec, SlotSpec, StageEngine
from .models import (
    MatchID,
    Participant,
    Stage,
    Tournament,
    TournamentID,
)
from .stage_generation_base import (
    StageGenerationPayload,
)
from .swiss_pairing import (
    build_follow_up_swiss_round_specs,
    build_initial_swiss_round_specs,
)
from .swiss_round_reconcile import reconcile_round_placeholders
from .swiss_stage_follow_up_parts import (
    _apply_seeded_swiss_specs,
    _get_swiss_matches_after_round,
    _group_swiss_matches_by_round_no,
    _has_occupied_swiss_slots,
    _is_swiss_round_completed,
    _load_swiss_stage_match_data,
    _SwissStageMatchData,
)
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
        pools = _build_swiss_round_pools(counts_by_record)

        rounds.append({'round_no': round_no, 'pools': pools})

        counts_by_record = _advance_swiss_record_counts(pools, threshold)

    return rounds


def _build_swiss_round_pools(
    counts_by_record: dict[tuple[int, int], int],
) -> list[dict[str, Any]]:
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
    return pools


def _advance_swiss_record_counts(
    pools: list[dict[str, Any]], threshold: int
) -> dict[tuple[int, int], int]:
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

    return dict(next_counts)


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


def seed_swiss_follow_up_rounds(
    *,
    tournament_id: TournamentID,
    stage: Stage,
) -> list[MatchID]:
    newly_ready_match_ids: list[MatchID] = []
    match_data = _load_swiss_stage_match_data(tournament_id, stage)
    if match_data is None:
        return []

    participants = match_data.participants

    round_count = get_round_count_for_swiss_stage(
        stage, participant_count=len(participants)
    )
    layout = build_swiss_round_layout(len(participants), round_count)
    matches_by_round_no = _group_swiss_matches_by_round_no(
        match_data.db_matches
    )

    for round_layout in layout[1:]:
        if not _seed_swiss_follow_up_round(
            tournament_id,
            round_layout['round_no'],
            match_data,
            matches_by_round_no,
            round_count,
            newly_ready_match_ids,
        ):
            # Later rounds have to wait, but the rounds seeded so far
            # must still be announced.
            break

    return newly_ready_match_ids


def _seed_swiss_follow_up_round(
    tournament_id: TournamentID,
    round_no: int,
    match_data: _SwissStageMatchData,
    matches_by_round_no: dict[int, list[DbNetsessionTourneyMatch]],
    round_count: int,
    newly_ready_match_ids: list[MatchID],
) -> bool:
    """Seed one follow-up round if possible.

    Return `False` if seeding has to stop altogether (previous round not
    completed or no target matches), `True` otherwise.
    """
    slots_by_match_id = match_data.slots_by_match_id
    previous_round_matches = matches_by_round_no.get(round_no - 1, [])
    if not _is_swiss_round_completed(previous_round_matches):
        return False

    target_matches = sorted(
        matches_by_round_no.get(round_no, []),
        key=lambda match: match.match_no,
    )
    if not target_matches:
        return False

    if _has_occupied_swiss_slots(target_matches, slots_by_match_id):
        return True

    seeded_specs = build_follow_up_swiss_round_specs(
        participants=match_data.participants,
        db_matches=match_data.db_matches,
        slots_by_match_id=slots_by_match_id,
        results_by_match_id=match_data.results_by_match_id,
        next_round_no=round_no,
        first_match_no=target_matches[0].match_no,
        round_count=round_count,
    )
    if not seeded_specs:
        return True

    target_matches = reconcile_round_placeholders(
        target_matches,
        _get_swiss_matches_after_round(matches_by_round_no, round_no),
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
    return True

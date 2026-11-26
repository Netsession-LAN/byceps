"""
byceps.services.netsession_tourney.stage_ranking_rows_outcome
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Reading a match result for the ranking rows: the outcome of a match
and the duel result it adds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .dbmodels import (
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
)
from .models import ParticipantID
from .score_parsing import (
    is_walkover_score_json,
    parse_match_result_slot_scores,
    parse_numeric_score_value,
)


@dataclass(frozen=True, kw_only=True)
class _MatchOutcome:
    """What a match result means for the ranking rows."""

    real_match_slots: list[DbNetsessionTourneyMatchSlot]
    real_participant_ids: list[ParticipantID]
    winner_participant_id: ParticipantID | None
    score_slots: dict[int, str]
    skip_rounds: bool
    placement_by_slot_no: dict[int, int]
    points_by_slot_no: dict[int, int]

    def is_rankable_duel(self) -> bool:
        """Tell whether the result counts as a head-to-head pairing."""
        return (
            len(self.real_participant_ids) == 2
            and self.winner_participant_id in self.real_participant_ids
            and not self.skip_rounds
        )


def _read_match_outcome(
    db_result: DbNetsessionTourneyMatchResult,
    db_match_slots: list[DbNetsessionTourneyMatchSlot],
    *,
    is_swiss_stage: bool,
) -> _MatchOutcome:
    real_match_slots = [
        s for s in db_match_slots if s.participant_id is not None
    ]
    real_participant_ids = [s.participant_id for s in real_match_slots]
    winner_participant_id = _winner_participant_id(db_result, db_match_slots)
    score_slots = parse_match_result_slot_scores(
        real_match_slots,
        db_result.score_json,
        winner_slot=db_result.winner_slot,
    )
    skip_rounds = is_swiss_stage and is_walkover_score_json(
        db_result.score_json
    )

    ranking = db_result.ranking_json or {}
    return _MatchOutcome(
        real_match_slots=real_match_slots,
        real_participant_ids=real_participant_ids,
        winner_participant_id=winner_participant_id,
        score_slots=score_slots,
        skip_rounds=skip_rounds,
        placement_by_slot_no=_read_slot_numbers(
            ranking.get('placements'), db_match_slots
        ),
        points_by_slot_no=_read_slot_numbers(
            ranking.get('points'), db_match_slots
        ),
    )


def _add_duel_result(
    row: dict[str, Any],
    db_slot: DbNetsessionTourneyMatchSlot,
    outcome: _MatchOutcome,
) -> None:
    """Count win or loss, and (for two participants) the rounds."""
    real_participant_ids = outcome.real_participant_ids
    if outcome.winner_participant_id is None or len(real_participant_ids) < 2:
        return

    if db_slot.participant_id == outcome.winner_participant_id:
        row['wins'] += 1
        row['match_points'] += 3
    else:
        row['losses'] += 1

    if len(real_participant_ids) != 2 or outcome.skip_rounds:
        return

    _add_rounds(
        row, db_slot.slot_no, outcome.real_match_slots, outcome.score_slots
    )


def _winner_participant_id(db_result, db_match_slots):
    if db_result.winner_slot is None:
        return None
    return next(
        (
            s.participant_id
            for s in db_match_slots
            if s.slot_no == db_result.winner_slot
        ),
        None,
    )


def _slot_value(values: dict, slot_no: int):
    """Look a slot up by text key first, then by number."""
    value = values.get(str(slot_no))
    return value if value is not None else values.get(slot_no)


def _read_slot_numbers(raw, db_match_slots) -> dict[int, int]:
    if not isinstance(raw, dict):
        return {}
    numbers = {}
    for db_slot in db_match_slots:
        try:
            numbers[db_slot.slot_no] = int(_slot_value(raw, db_slot.slot_no))
        except TypeError, ValueError:
            continue
    return numbers


def _add_rounds(row, slot_no, real_match_slots, score_slots) -> None:
    round_wins = parse_numeric_score_value(_slot_value(score_slots, slot_no))
    round_losses = sum(
        parse_numeric_score_value(_slot_value(score_slots, other.slot_no))
        for other in real_match_slots
        if other.slot_no != slot_no
    )
    row['round_wins'] += round_wins
    row['round_losses'] += round_losses
    row['round_diff'] = row['round_wins'] - row['round_losses']

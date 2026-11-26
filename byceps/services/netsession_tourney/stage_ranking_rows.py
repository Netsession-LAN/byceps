"""
byceps.services.netsession_tourney.stage_ranking_rows
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ranking rows of a stage: one row per participant, filled from the match
results (points, wins, kills, placement, rounds, strength of schedule).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
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


def new_ranking_row(db_participant) -> dict[str, Any]:
    return {
        'total_points': 0,
        'points': 0,
        'wins': 0,
        'losses': 0,
        'match_points': 0,
        'round_wins': 0,
        'round_losses': 0,
        'round_diff': 0,
        'buchholz': 0,
        'opponent_wl_sum': 0,
        'second_order_sos': 0,
        'kills': 0,
        'placement': None,
        'seed': db_participant.seed,
        'created_at': db_participant.created_at,
    }


@dataclass(kw_only=True)
class RankingTally:
    """Rows plus who played whom, filled result by result."""

    rows_by_participant_id: dict[ParticipantID, dict[str, Any]]
    is_ffa_scoring_stage: bool
    is_swiss_stage: bool
    points_per_kill: int
    opponent_ids_by_participant_id: dict[ParticipantID, list[ParticipantID]] = (
        field(default_factory=lambda: defaultdict(list))
    )
    head_to_head_winner_id_by_pair: dict[
        frozenset[ParticipantID], ParticipantID
    ] = field(default_factory=dict)

    def add_result(
        self,
        db_result: DbNetsessionTourneyMatchResult,
        db_match_slots: list[DbNetsessionTourneyMatchSlot],
    ) -> None:
        real_match_slots = [
            s for s in db_match_slots if s.participant_id is not None
        ]
        real_participant_ids = [s.participant_id for s in real_match_slots]
        winner_participant_id = _winner_participant_id(
            db_result, db_match_slots
        )
        score_slots = parse_match_result_slot_scores(
            real_match_slots,
            db_result.score_json,
            winner_slot=db_result.winner_slot,
        )
        skip_rounds = self.is_swiss_stage and is_walkover_score_json(
            db_result.score_json
        )

        if (
            len(real_participant_ids) == 2
            and winner_participant_id in real_participant_ids
            and not skip_rounds
        ):
            self._record_pairing(real_participant_ids, winner_participant_id)

        ranking = db_result.ranking_json or {}
        placement_by_slot_no = _read_slot_numbers(
            ranking.get('placements'), db_match_slots
        )
        points_by_slot_no = _read_slot_numbers(
            ranking.get('points'), db_match_slots
        )

        for db_slot in db_match_slots:
            row = self.rows_by_participant_id.get(db_slot.participant_id)
            if db_slot.participant_id is None or row is None:
                continue

            if self.is_ffa_scoring_stage:
                self._add_ffa_scores(
                    row,
                    db_slot.slot_no,
                    score_slots,
                    points_by_slot_no,
                    placement_by_slot_no,
                )

            if winner_participant_id is None or len(real_participant_ids) < 2:
                continue

            if db_slot.participant_id == winner_participant_id:
                row['wins'] += 1
                row['match_points'] += 3
            else:
                row['losses'] += 1

            if len(real_participant_ids) != 2 or skip_rounds:
                continue

            _add_rounds(row, db_slot.slot_no, real_match_slots, score_slots)

    def add_strength_of_schedule(self) -> None:
        """Buchholz, opponents' win/loss sum and its second order."""
        rows = self.rows_by_participant_id
        opponents = self.opponent_ids_by_participant_id
        for participant_id, row in rows.items():
            opponent_rows = [
                rows.get(o, {}) for o in opponents.get(participant_id, [])
            ]
            row['buchholz'] = sum(r.get('wins', 0) for r in opponent_rows)
            row['opponent_wl_sum'] = sum(
                r.get('wins', 0) - r.get('losses', 0) for r in opponent_rows
            )
        for participant_id, row in rows.items():
            row['second_order_sos'] = sum(
                rows.get(o, {}).get('opponent_wl_sum', 0)
                for o in opponents.get(participant_id, [])
            )

    def _record_pairing(self, participant_ids, winner_participant_id) -> None:
        participant_a, participant_b = participant_ids
        self.opponent_ids_by_participant_id[participant_a].append(participant_b)
        self.opponent_ids_by_participant_id[participant_b].append(participant_a)
        self.head_to_head_winner_id_by_pair[frozenset(participant_ids)] = (
            winner_participant_id
        )

    def _add_ffa_scores(
        self, row, slot_no, score_slots, points_by_slot_no, placement_by_slot_no
    ) -> None:
        row['points'] += points_by_slot_no.get(slot_no, 0)
        try:
            row['kills'] += int(_slot_value(score_slots, slot_no))
        except TypeError, ValueError:
            pass
        row['total_points'] = (
            row['points'] + row['kills'] * self.points_per_kill
        )

        placement = placement_by_slot_no.get(slot_no)
        if placement is not None and (
            row['placement'] is None or placement < row['placement']
        ):
            row['placement'] = placement


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

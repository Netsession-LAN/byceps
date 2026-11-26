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
from .stage_ranking_rows_outcome import (
    _add_duel_result,
    _MatchOutcome,
    _read_match_outcome,
    _slot_value,
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
        outcome = _read_match_outcome(
            db_result, db_match_slots, is_swiss_stage=self.is_swiss_stage
        )

        if outcome.is_rankable_duel():
            self._record_pairing(
                outcome.real_participant_ids, outcome.winner_participant_id
            )

        for db_slot in db_match_slots:
            self._add_slot_result(db_slot, outcome)

    def _add_slot_result(
        self, db_slot: DbNetsessionTourneyMatchSlot, outcome: _MatchOutcome
    ) -> None:
        row = self.rows_by_participant_id.get(db_slot.participant_id)
        if db_slot.participant_id is None or row is None:
            return

        if self.is_ffa_scoring_stage:
            self._add_ffa_scores(
                row,
                db_slot.slot_no,
                outcome.score_slots,
                outcome.points_by_slot_no,
                outcome.placement_by_slot_no,
            )

        _add_duel_result(row, db_slot, outcome)

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

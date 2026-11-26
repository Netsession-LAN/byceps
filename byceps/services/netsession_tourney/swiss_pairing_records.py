"""
byceps.services.netsession_tourney.swiss_pairing_records
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Swiss records: wins, losses, opponents and byes per participant, read
from the previous rounds.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
)
from .models import (
    MatchID,
    Participant,
    ParticipantID,
)


@dataclass(kw_only=True)
class _SwissRecords:
    """Wins, losses, past opponents and byes per participant."""

    wins: dict[ParticipantID, int]
    losses: dict[ParticipantID, int]
    opponents: dict[ParticipantID, set[ParticipantID]]
    bye_counts: dict[ParticipantID, int]

    @classmethod
    def tally(
        cls, participants, db_matches, slots_by_match_id, results_by_match_id
    ) -> _SwissRecords:
        participant_by_id = {p.id: p for p in participants}
        records = cls(
            wins=defaultdict(int),
            losses=defaultdict(int),
            opponents=defaultdict(set),
            bye_counts=defaultdict(int),
        )
        for db_match in db_matches:
            records._add_match(
                db_match,
                slots_by_match_id.get(db_match.id, []),
                results_by_match_id,
                participant_by_id,
            )
        return records

    def _add_match(
        self,
        db_match: DbNetsessionTourneyMatch,
        db_slots: list[DbNetsessionTourneyMatchSlot],
        results_by_match_id: dict[MatchID, DbNetsessionTourneyMatchResult],
        participant_by_id: dict[ParticipantID, Participant],
    ) -> None:
        participant_ids = [
            s.participant_id
            for s in db_slots
            if s.participant_id in participant_by_id
        ]
        if not participant_ids:
            return

        self._add_bye_or_pairing(participant_ids)

        winner_participant_id = _find_swiss_winner_participant_id(
            results_by_match_id.get(db_match.id), db_slots
        )
        if winner_participant_id not in participant_by_id:
            return

        self._add_win_and_losses(winner_participant_id, participant_ids)

    def _add_bye_or_pairing(self, participant_ids: list[ParticipantID]) -> None:
        if len(participant_ids) == 1:
            self.bye_counts[participant_ids[0]] += 1
        if len(participant_ids) == 2:
            participant_a, participant_b = participant_ids
            self.opponents[participant_a].add(participant_b)
            self.opponents[participant_b].add(participant_a)

    def _add_win_and_losses(
        self,
        winner_participant_id: ParticipantID,
        participant_ids: list[ParticipantID],
    ) -> None:
        self.wins[winner_participant_id] += 1
        for participant_id in participant_ids:
            if participant_id != winner_participant_id:
                self.losses[participant_id] += 1

    def record_of(self, participant) -> tuple[int, int]:
        return self.wins[participant.id], self.losses[participant.id]

    def still_playing_ranked(
        self, participants, *, threshold: int, next_round_no: int
    ) -> list[Participant]:
        """Participants below the win/loss threshold that played every
        round so far, best record first."""
        return sorted(
            [
                p
                for p in participants
                if self.wins[p.id] < threshold
                and self.losses[p.id] < threshold
                and self.wins[p.id] + self.losses[p.id] == next_round_no - 1
            ],
            key=lambda p: (
                -self.wins[p.id],
                self.losses[p.id],
                p.seed if p.seed is not None else 999_999,
                p.name.lower(),
                str(p.id),
            ),
        )


def _find_swiss_winner_participant_id(
    db_result: DbNetsessionTourneyMatchResult | None,
    db_slots: list[DbNetsessionTourneyMatchSlot],
) -> ParticipantID | None:
    if db_result is None or db_result.winner_slot is None:
        return None

    return next(
        (
            s.participant_id
            for s in db_slots
            if s.slot_no == db_result.winner_slot
        ),
        None,
    )

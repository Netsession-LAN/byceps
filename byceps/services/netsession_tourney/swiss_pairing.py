"""
byceps.services.netsession_tourney.swiss_pairing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Swiss pairings: first round, follow-up rounds by record, byes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
)
from .engines.base import MatchSpec, SlotSpec
from .models import (
    MatchID,
    Participant,
    ParticipantID,
)
from .swiss_thresholds import (
    get_swiss_threshold_for_round_count,
)


def build_initial_swiss_round_specs(
    participants: list[Participant],
) -> list[MatchSpec]:
    if len(participants) < 2:
        return []

    ordered = list(participants)
    bye_participant = None
    if len(ordered) % 2 == 1:
        bye_participant = ordered.pop()

    midpoint = len(ordered) // 2
    top_half = ordered[:midpoint]
    bottom_half = ordered[midpoint:]

    specs: list[MatchSpec] = []
    match_no = 1
    for participant_a, participant_b in zip(
        top_half, bottom_half, strict=False
    ):
        specs.append(
            MatchSpec(
                round_no=1,
                match_no=match_no,
                state='ready',
                slots=[
                    SlotSpec(
                        slot_no=1,
                        participant_id=participant_a.id,
                        source_match_no=None,
                    ),
                    SlotSpec(
                        slot_no=2,
                        participant_id=participant_b.id,
                        source_match_no=None,
                    ),
                ],
            )
        )
        match_no += 1

    if bye_participant is not None:
        specs.append(
            MatchSpec(
                round_no=1,
                match_no=match_no,
                state='pending',
                slots=[
                    SlotSpec(
                        slot_no=1,
                        participant_id=bye_participant.id,
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

    return specs


def build_follow_up_swiss_round_specs(
    *,
    participants: list[Participant],
    db_matches: list[DbNetsessionTourneyMatch],
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]],
    results_by_match_id: dict[MatchID, DbNetsessionTourneyMatchResult],
    next_round_no: int,
    first_match_no: int,
    round_count: int,
) -> list[MatchSpec]:
    records = _SwissRecords.tally(
        participants, db_matches, slots_by_match_id, results_by_match_id
    )
    threshold = get_swiss_threshold_for_round_count(round_count)
    ranked_participants = records.still_playing_ranked(
        participants, threshold=threshold, next_round_no=next_round_no
    )

    bye_participant, ranked_participants = _take_out_swiss_bye(
        ranked_participants, records
    )

    pairs, carry_over = _pair_by_record(ranked_participants, records)

    bye_participant = _place_swiss_carry_over(
        pairs, carry_over, bye_participant, records
    )

    return _round_specs(pairs, bye_participant, next_round_no, first_match_no)


def _take_out_swiss_bye(
    ranked_participants: list[Participant], records: _SwissRecords
) -> tuple[Participant | None, list[Participant]]:
    """With an odd number of participants, pick the one who gets a bye.
    Return it (or `None`) and the remaining participants."""
    if len(ranked_participants) % 2 == 0:
        return None, ranked_participants

    bye_participant = _select_swiss_bye_participant(
        ranked_participants, records.bye_counts
    )
    remaining_participants = [
        p for p in ranked_participants if p.id != bye_participant.id
    ]
    return bye_participant, remaining_participants


def _place_swiss_carry_over(
    pairs: list[tuple[Participant, Participant]],
    carry_over: list[Participant],
    bye_participant: Participant | None,
    records: _SwissRecords,
) -> Participant | None:
    """Give a left-over participant the bye (if still free) or pair the
    last two left-over participants. Return the bye participant."""
    if not carry_over:
        return bye_participant

    if bye_participant is None:
        bye_participant = _select_swiss_bye_participant(
            carry_over, records.bye_counts
        )
        carry_over = [p for p in carry_over if p.id != bye_participant.id]
    if len(carry_over) == 2:
        pairs.append((carry_over[0], carry_over[1]))

    return bye_participant


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


def _pair_by_record(
    ranked_participants: list[Participant], records: _SwissRecords
) -> tuple[list[tuple[Participant, Participant]], list[Participant]]:
    """Pair participants with the same record who have not met yet; an odd
    one out moves down to the next record group."""
    grouped_participants = defaultdict(list)
    for participant in ranked_participants:
        grouped_participants[records.record_of(participant)].append(participant)

    pairs: list[tuple[Participant, Participant]] = []
    carry_over: list[Participant] = []
    for record in sorted(
        grouped_participants, key=lambda item: (-item[0], item[1])
    ):
        current_group = carry_over + grouped_participants[record]
        carry_over = _pair_record_group(current_group, records.opponents, pairs)

    return pairs, carry_over


def _pair_record_group(
    current_group: list[Participant],
    opponents_by_participant_id: dict[ParticipantID, set[ParticipantID]],
    pairs: list[tuple[Participant, Participant]],
) -> list[Participant]:
    """Append the pairs of one record group; return who is carried over to
    the next group."""
    carry_over: list[Participant] = []

    while current_group:
        if len(current_group) % 2 == 1:
            carry_over = [current_group.pop()]

        pairing = _find_swiss_pairing_for_group(
            current_group, opponents_by_participant_id
        )
        if pairing is not None:
            pairs.extend(pairing)
            current_group = []
            continue

        if len(current_group) <= 2:
            if len(current_group) == 2:
                pairs.append((current_group[0], current_group[1]))
            current_group = []
            continue

        carry_over = [current_group.pop()]

    return carry_over


def _round_specs(
    pairs, bye_participant, next_round_no: int, first_match_no: int
) -> list[MatchSpec]:
    specs = [
        MatchSpec(
            round_no=next_round_no,
            match_no=first_match_no + index,
            state='ready',
            slots=[
                SlotSpec(slot_no=1, participant_id=a.id, source_match_no=None),
                SlotSpec(slot_no=2, participant_id=b.id, source_match_no=None),
            ],
        )
        for index, (a, b) in enumerate(pairs)
    ]
    if bye_participant is not None:
        specs.append(
            MatchSpec(
                round_no=next_round_no,
                match_no=first_match_no + len(pairs),
                state='pending',
                slots=[
                    SlotSpec(
                        slot_no=1,
                        participant_id=bye_participant.id,
                        source_match_no=None,
                    ),
                    SlotSpec(
                        slot_no=2, participant_id=None, source_match_no=None
                    ),
                ],
            )
        )
    return specs


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


def _select_swiss_bye_participant(
    participants: list[Participant],
    bye_count_by_participant_id: dict[ParticipantID, int],
) -> Participant:
    lowest_bye_count = min(
        bye_count_by_participant_id.get(participant.id, 0)
        for participant in participants
    )
    for participant in reversed(participants):
        if (
            bye_count_by_participant_id.get(participant.id, 0)
            == lowest_bye_count
        ):
            return participant

    return participants[-1]


def _find_swiss_pairing_for_group(
    participants: list[Participant],
    opponents_by_participant_id: dict[ParticipantID, set[ParticipantID]],
) -> list[tuple[Participant, Participant]] | None:
    if not participants:
        return []
    if len(participants) % 2 == 1:
        return None

    first = participants[0]
    for index, candidate in enumerate(participants[1:], start=1):
        if candidate.id in opponents_by_participant_id.get(first.id, set()):
            continue

        remainder = participants[1:index] + participants[index + 1 :]
        remainder_pairing = _find_swiss_pairing_for_group(
            remainder, opponents_by_participant_id
        )
        if remainder_pairing is not None:
            return [(first, candidate)] + remainder_pairing

    # Fall back to the least bad option if rematches are unavoidable.
    candidate = participants[1]
    remainder = participants[2:]
    remainder_pairing = _find_swiss_pairing_for_group(
        remainder, opponents_by_participant_id
    )
    if remainder_pairing is None:
        return None
    return [(first, candidate)] + remainder_pairing

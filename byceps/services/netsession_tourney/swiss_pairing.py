"""
byceps.services.netsession_tourney.swiss_pairing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Swiss pairings: first round, follow-up rounds by record, byes.
"""

from __future__ import annotations

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
from .swiss_pairing_groups import (
    _pair_by_record,
)
from .swiss_pairing_records import (
    _SwissRecords,
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

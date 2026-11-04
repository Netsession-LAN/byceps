"""
byceps.services.netsession_tourney.swiss_pairing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Swiss pairings: first round, follow-up rounds by record, byes.
"""

from __future__ import annotations

from collections import defaultdict

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
    _get_swiss_threshold_for_round_count,
)


def _build_initial_swiss_round_specs(
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
    for participant_a, participant_b in zip(top_half, bottom_half, strict=False):
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


def _build_follow_up_swiss_round_specs(
    *,
    participants: list[Participant],
    db_matches: list[DbNetsessionTourneyMatch],
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]],
    results_by_match_id: dict[MatchID, DbNetsessionTourneyMatchResult],
    next_round_no: int,
    first_match_no: int,
    round_count: int,
) -> list[MatchSpec]:
    participant_by_id = {participant.id: participant for participant in participants}
    threshold = _get_swiss_threshold_for_round_count(round_count)
    wins_by_participant_id: dict[ParticipantID, int] = defaultdict(int)
    losses_by_participant_id: dict[ParticipantID, int] = defaultdict(int)
    opponents_by_participant_id: dict[ParticipantID, set[ParticipantID]] = defaultdict(
        set
    )
    bye_count_by_participant_id: dict[ParticipantID, int] = defaultdict(int)

    for db_match in db_matches:
        db_slots = slots_by_match_id.get(db_match.id, [])
        participant_ids = [
            db_slot.participant_id
            for db_slot in db_slots
            if db_slot.participant_id in participant_by_id
        ]
        if not participant_ids:
            continue

        if len(participant_ids) == 1:
            bye_count_by_participant_id[participant_ids[0]] += 1

        if len(participant_ids) == 2:
            participant_a, participant_b = participant_ids
            opponents_by_participant_id[participant_a].add(participant_b)
            opponents_by_participant_id[participant_b].add(participant_a)

        db_result = results_by_match_id.get(db_match.id)
        if db_result is None or db_result.winner_slot is None:
            continue

        winner_participant_id = next(
            (
                db_slot.participant_id
                for db_slot in db_slots
                if db_slot.slot_no == db_result.winner_slot
            ),
            None,
        )
        if winner_participant_id not in participant_by_id:
            continue

        wins_by_participant_id[winner_participant_id] += 1
        for participant_id in participant_ids:
            if participant_id != winner_participant_id:
                losses_by_participant_id[participant_id] += 1

    ranked_participants = sorted(
        [
            participant
            for participant in participants
            if wins_by_participant_id[participant.id] < threshold
            and losses_by_participant_id[participant.id] < threshold
            and (
                wins_by_participant_id[participant.id]
                + losses_by_participant_id[participant.id]
                == next_round_no - 1
            )
        ],
        key=lambda participant: (
            -wins_by_participant_id[participant.id],
            losses_by_participant_id[participant.id],
            participant.seed if participant.seed is not None else 999_999,
            participant.name.lower(),
            str(participant.id),
        ),
    )

    bye_participant = None
    if len(ranked_participants) % 2 == 1:
        bye_participant = _select_swiss_bye_participant(
            ranked_participants, bye_count_by_participant_id
        )
        ranked_participants = [
            participant
            for participant in ranked_participants
            if participant.id != bye_participant.id
        ]

    grouped_participants = defaultdict(list)
    for participant in ranked_participants:
        grouped_participants[
            (
                wins_by_participant_id[participant.id],
                losses_by_participant_id[participant.id],
            )
        ].append(participant)

    pairs: list[tuple[Participant, Participant]] = []
    carry_over: list[Participant] = []
    for record in sorted(
        grouped_participants.keys(), key=lambda item: (-item[0], item[1])
    ):
        current_group = carry_over + grouped_participants[record]
        carry_over = []

        while current_group:
            if len(current_group) % 2 == 1:
                carry_over = [current_group.pop()]

            pairing = _find_swiss_pairing_for_group(
                current_group,
                opponents_by_participant_id,
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

        if carry_over:
            continue

    if carry_over:
        if bye_participant is None:
            bye_participant = _select_swiss_bye_participant(
                carry_over, bye_count_by_participant_id
            )
            carry_over = [
                participant
                for participant in carry_over
                if participant.id != bye_participant.id
            ]
        if len(carry_over) == 2:
            pairs.append((carry_over[0], carry_over[1]))

    specs: list[MatchSpec] = []
    match_no = first_match_no
    for participant_a, participant_b in pairs:
        specs.append(
            MatchSpec(
                round_no=next_round_no,
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
                round_no=next_round_no,
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

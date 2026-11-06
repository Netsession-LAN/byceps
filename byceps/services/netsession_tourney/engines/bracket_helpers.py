"""
byceps.services.netsession_tourney.engines.bracket_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Pure helpers that build the match specs of single and double elimination
brackets for the stage engines, plus shared slot and seeding helpers.
"""

from __future__ import annotations

import math
from typing import TypeVar

from ..models import ParticipantID
from .base import MatchSpec, SlotSpec


T = TypeVar('T')


# -------------------------------------------------------------------- #
# single elimination


def build_single_elimination_specs(
    bracket_slots: list[ParticipantID | None],
    *,
    include_consolation_final: bool,
) -> list[MatchSpec]:
    specs = _build_seeded_first_round_specs(bracket_slots)
    first_round_match_numbers = [spec.match_no for spec in specs]
    specs.extend(
        _build_single_elimination_follow_up_specs(
            first_round_match_numbers,
            first_match_no=len(specs) + 1,
            include_consolation_final=include_consolation_final,
        )
    )
    return specs


def _build_seeded_first_round_specs(
    bracket_slots: list[ParticipantID | None],
) -> list[MatchSpec]:
    specs: list[MatchSpec] = []
    match_no = 1
    for index in range(len(bracket_slots) // 2):
        p1 = bracket_slots[index * 2]
        p2 = bracket_slots[index * 2 + 1]
        state = 'ready' if p1 and p2 else 'pending'
        specs.append(
            MatchSpec(
                round_no=1,
                match_no=match_no,
                state=state,
                slots=_seeded_slots(p1, p2),
            )
        )
        match_no += 1
    return specs


def _build_single_elimination_follow_up_specs(
    previous_round_match_numbers: list[int],
    *,
    first_match_no: int,
    include_consolation_final: bool,
) -> list[MatchSpec]:
    specs: list[MatchSpec] = []
    round_no = 2
    match_no = first_match_no
    while len(previous_round_match_numbers) > 1:
        current_round_match_numbers = []
        is_final_round = len(previous_round_match_numbers) == 2
        for index in range(0, len(previous_round_match_numbers), 2):
            specs.append(
                MatchSpec(
                    round_no=round_no,
                    match_no=match_no,
                    state='pending',
                    slots=[
                        SlotSpec(
                            slot_no=1,
                            participant_id=None,
                            source_match_no=previous_round_match_numbers[index],
                        ),
                        SlotSpec(
                            slot_no=2,
                            participant_id=None,
                            source_match_no=previous_round_match_numbers[
                                index + 1
                            ],
                        ),
                    ],
                )
            )
            current_round_match_numbers.append(match_no)
            match_no += 1

        if include_consolation_final and is_final_round:
            semifinal_1, semifinal_2 = previous_round_match_numbers
            specs.append(
                MatchSpec(
                    round_no=round_no,
                    match_no=match_no,
                    state='pending',
                    slots=[
                        _sourced_slot(1, semifinal_1, 'loser'),
                        _sourced_slot(2, semifinal_2, 'loser'),
                    ],
                )
            )
            match_no += 1

        previous_round_match_numbers = current_round_match_numbers
        round_no += 1

    return specs


# -------------------------------------------------------------------- #
# double elimination


_SpecsByMatchNo = dict[int, tuple[list[SlotSpec], str]]


def build_double_elimination_specs(
    bracket_slots: list[ParticipantID | None],
    *,
    include_double_grand_final: bool,
) -> list[MatchSpec]:
    """Build a double elimination bracket for more than two bracket slots."""
    specs_by_match_no: _SpecsByMatchNo = {}

    wb_round_match_nos, match_no = _add_winner_bracket(
        specs_by_match_no, bracket_slots
    )

    if len(wb_round_match_nos) < 2:
        # Should not happen for bracket_size > 2, but keep safe.
        return _with_computed_round_numbers(specs_by_match_no)

    lb_final_match_no, match_no = _add_loser_bracket(
        specs_by_match_no, wb_round_match_nos, match_no
    )
    wb_final_match_no = wb_round_match_nos[-1][0]

    # Grand Final #1.
    specs_by_match_no[match_no] = (
        [
            _sourced_slot(1, wb_final_match_no, 'winner'),
            _sourced_slot(2, lb_final_match_no, 'winner'),
        ],
        'pending',
    )
    grand_final_match_no = match_no
    match_no += 1

    if include_double_grand_final:
        # Optional bracket-reset match:
        # If the LB winner wins Grand Final #1, both participants have one
        # loss and must play once more.
        specs_by_match_no[match_no] = (
            [
                _sourced_slot(1, grand_final_match_no, 'winner'),
                _sourced_slot(2, grand_final_match_no, 'loser'),
            ],
            'pending',
        )

    return _with_computed_round_numbers(specs_by_match_no)


def _add_winner_bracket(
    specs_by_match_no: _SpecsByMatchNo,
    bracket_slots: list[ParticipantID | None],
) -> tuple[list[list[int]], int]:
    """Add all winner bracket rounds; return their match numbers per round
    and the next free match number."""
    match_no = 1
    wb_round_match_nos: list[list[int]] = []

    # WB round 1 from seeded participants.
    wb_round_1: list[int] = []
    for index in range(0, len(bracket_slots), 2):
        p1 = bracket_slots[index]
        p2 = bracket_slots[index + 1]
        state = 'ready' if p1 and p2 else 'pending'
        specs_by_match_no[match_no] = (
            _seeded_slots(p1, p2),
            state,
        )
        wb_round_1.append(match_no)
        match_no += 1
    wb_round_match_nos.append(wb_round_1)

    # WB follow-up rounds.
    previous_wb_round = wb_round_1
    while len(previous_wb_round) > 1:
        current_wb_round, match_no = _add_paired_round(
            specs_by_match_no, previous_wb_round, match_no, 'winner'
        )
        wb_round_match_nos.append(current_wb_round)
        previous_wb_round = current_wb_round

    return wb_round_match_nos, match_no


def _add_loser_bracket(
    specs_by_match_no: _SpecsByMatchNo,
    wb_round_match_nos: list[list[int]],
    match_no: int,
) -> tuple[int, int]:
    """Add all loser bracket rounds; return the loser bracket final's match
    number and the next free match number."""
    # LB construction.
    lb_previous_round, match_no = _add_paired_round(
        specs_by_match_no, wb_round_match_nos[0], match_no, 'loser'
    )

    # Interleave remaining WB rounds into LB, crossed so that WB losers
    # meet players from the other side of the bracket first.
    for wb_round_index in range(1, len(wb_round_match_nos)):
        wb_round = _crossed_for_loser_bracket(
            wb_round_match_nos[wb_round_index], wb_round_index
        )

        while len(lb_previous_round) > len(wb_round):
            lb_previous_round, match_no = _add_paired_round(
                specs_by_match_no, lb_previous_round, match_no, 'winner'
            )

        injected_round: list[int] = []
        for index, wb_match_no in enumerate(wb_round):
            lb_match_no = lb_previous_round[index]
            specs_by_match_no[match_no] = (
                [
                    _sourced_slot(1, lb_match_no, 'winner'),
                    _sourced_slot(2, wb_match_no, 'loser'),
                ],
                'pending',
            )
            injected_round.append(match_no)
            match_no += 1
        lb_previous_round = injected_round

    return lb_previous_round[0], match_no


def _crossed_for_loser_bracket(
    wb_round: list[int], injection_index: int
) -> list[int]:
    """Order in which a WB round's losers drop into the loser bracket.

    Without crossing, a WB loser landed next to players from their own
    part of the bracket and often met someone again right away. Odd
    injections are reversed, even ones reversed per half (simulated: early
    LB rematches 8 players 75 % -> 25 %, 16 players 98 % -> 38 %).
    """
    if injection_index % 2 == 1:
        return list(reversed(wb_round))
    half = len(wb_round) // 2
    return list(reversed(wb_round[:half])) + list(reversed(wb_round[half:]))


def _add_paired_round(
    specs_by_match_no: _SpecsByMatchNo,
    source_match_nos: list[int],
    match_no: int,
    outcome: str,
) -> tuple[list[int], int]:
    """Pair up consecutive source matches, taking the given outcome of both;
    return the new round's match numbers and the next free match number."""
    current_round: list[int] = []
    for index in range(0, len(source_match_nos), 2):
        source_a = source_match_nos[index]
        source_b = source_match_nos[index + 1]
        specs_by_match_no[match_no] = (
            [
                _sourced_slot(1, source_a, outcome),
                _sourced_slot(2, source_b, outcome),
            ],
            'pending',
        )
        current_round.append(match_no)
        match_no += 1
    return current_round, match_no


# -------------------------------------------------------------------- #
# shared building blocks


def _seeded_slots(
    participant_1: ParticipantID | None, participant_2: ParticipantID | None
) -> list[SlotSpec]:
    return [
        SlotSpec(slot_no=1, participant_id=participant_1, source_match_no=None),
        SlotSpec(slot_no=2, participant_id=participant_2, source_match_no=None),
    ]


def _sourced_slot(slot_no: int, source_match_no: int, outcome: str) -> SlotSpec:
    return SlotSpec(
        slot_no=slot_no,
        participant_id=None,
        source_match_no=source_match_no,
        source_outcome=outcome,
    )


def _chunked_evenly(items: list[T], chunk_count: int) -> list[list[T]]:
    if chunk_count <= 0:
        return []

    chunk_sizes = _distribute_evenly(len(items), chunk_count)
    chunks: list[list[T]] = []
    offset = 0
    for chunk_size in chunk_sizes:
        chunks.append(items[offset : offset + chunk_size])
        offset += chunk_size

    return [chunk for chunk in chunks if chunk]


def _distribute_evenly(total: int, bucket_count: int) -> list[int]:
    if bucket_count <= 0:
        return []

    base = total // bucket_count
    remainder = total % bucket_count
    return [
        base + (1 if index < remainder else 0) for index in range(bucket_count)
    ]


def _build_seeded_bracket_slots(
    participant_ids: list[ParticipantID],
) -> list[ParticipantID | None]:
    sorted_participants = list(participant_ids)
    bracket_size = _next_power_of_two(len(sorted_participants))
    seed_order = _build_single_elimination_seed_positions(bracket_size)

    return [
        (
            sorted_participants[seed_no - 1]
            if seed_no <= len(sorted_participants)
            else None
        )
        for seed_no in seed_order
    ]


def _with_computed_round_numbers(
    specs_by_match_no: dict[int, tuple[list[SlotSpec], str]],
) -> list[MatchSpec]:
    round_no_by_match_no: dict[int, int] = {}

    def get_round_no(match_no: int) -> int:
        existing = round_no_by_match_no.get(match_no)
        if existing is not None:
            return existing

        slots, _ = specs_by_match_no[match_no]
        source_match_nos = [
            slot.source_match_no
            for slot in slots
            if slot.source_match_no is not None
        ]
        if not source_match_nos:
            round_no = 1
        else:
            round_no = (
                max(get_round_no(source) for source in source_match_nos) + 1
            )

        round_no_by_match_no[match_no] = round_no
        return round_no

    return [
        MatchSpec(
            round_no=get_round_no(match_no),
            match_no=match_no,
            slots=slots,
            state=state,
        )
        for match_no, (slots, state) in sorted(specs_by_match_no.items())
    ]


def _next_power_of_two(value: int) -> int:
    if value <= 1:
        return 1
    return int(math.pow(2, math.ceil(math.log2(value))))


def _build_single_elimination_seed_positions(bracket_size: int) -> list[int]:
    if bracket_size <= 1:
        return [1]

    positions = [1, 2]
    while len(positions) < bracket_size:
        current_size = len(positions) * 2
        expanded: list[int] = []
        for position in positions:
            expanded.append(position)
            expanded.append(current_size + 1 - position)
        positions = expanded

    return positions

"""
byceps.services.netsession_tourney.engines.bracket_helpers_slots
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Shared slot, seeding and grouping helpers for the bracket specs and
the stage engines.
"""

from __future__ import annotations

import math
from typing import TypeVar

from byceps.services.netsession_tourney.models import ParticipantID

from .base import MatchSpec, SlotSpec


T = TypeVar('T')


def seeded_slots(
    participant_1: ParticipantID | None, participant_2: ParticipantID | None
) -> list[SlotSpec]:
    return [
        SlotSpec(slot_no=1, participant_id=participant_1, source_match_no=None),
        SlotSpec(slot_no=2, participant_id=participant_2, source_match_no=None),
    ]


def sourced_slot(slot_no: int, source_match_no: int, outcome: str) -> SlotSpec:
    return SlotSpec(
        slot_no=slot_no,
        participant_id=None,
        source_match_no=source_match_no,
        source_outcome=outcome,
    )


def chunked_evenly(items: list[T], chunk_count: int) -> list[list[T]]:
    if chunk_count <= 0:
        return []

    chunk_sizes = distribute_evenly(len(items), chunk_count)
    chunks: list[list[T]] = []
    offset = 0
    for chunk_size in chunk_sizes:
        chunks.append(items[offset : offset + chunk_size])
        offset += chunk_size

    return [chunk for chunk in chunks if chunk]


def snake_groups(items: list[T], group_count: int) -> list[list[T]]:
    """Deal items (ordered by seed) into groups in snake order: A B C, C B
    A, A B C … so the strongest do not all land in the first group."""
    groups: list[list[T]] = [[] for _ in range(max(group_count, 0))]
    if not groups:
        return []
    for index, item in enumerate(items):
        round_index, position = divmod(index, group_count)
        if round_index % 2 == 1:
            position = group_count - 1 - position
        groups[position].append(item)
    return [group for group in groups if group]


def distribute_evenly(total: int, bucket_count: int) -> list[int]:
    if bucket_count <= 0:
        return []

    base = total // bucket_count
    remainder = total % bucket_count
    return [
        base + (1 if index < remainder else 0) for index in range(bucket_count)
    ]


def build_seeded_bracket_slots(
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


def with_computed_round_numbers(
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

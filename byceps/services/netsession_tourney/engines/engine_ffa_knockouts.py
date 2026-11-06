"""
byceps.services.netsession_tourney.engines.engine_ffa_knockouts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Pure helpers that build the match specs of FFA knockouts (generic and
FlatOut 2) for the stage engines.
"""

from __future__ import annotations

import math

from ..models import ParticipantID
from .base import MatchSpec, SlotSpec
from .bracket_helpers import chunked_evenly


def build_ffa_first_round_specs(
    participant_ids: list[ParticipantID], max_players: int
) -> list[MatchSpec]:
    """Split the participants evenly into first round matches of at most
    `max_players` participants each."""
    specs: list[MatchSpec] = []
    match_no = 1
    initial_match_count = math.ceil(len(participant_ids) / max_players)
    for chunk in chunked_evenly(list(participant_ids), initial_match_count):
        slots = [
            SlotSpec(
                slot_no=index + 1,
                participant_id=participant_id,
                source_match_no=None,
            )
            for index, participant_id in enumerate(chunk)
        ]
        if len(slots) == 1:
            slots.append(
                SlotSpec(
                    slot_no=2,
                    participant_id=None,
                    source_match_no=None,
                )
            )

        specs.append(
            MatchSpec(
                round_no=1,
                match_no=match_no,
                state='ready' if len(chunk) >= 2 else 'pending',
                slots=slots,
            )
        )
        match_no += 1
    return specs


def build_ffa_knockout_follow_up_specs(
    previous_round_match_nos: list[int],
    *,
    first_match_no: int,
    max_players: int,
) -> list[MatchSpec]:
    specs: list[MatchSpec] = []
    match_no = first_match_no
    round_no = 2
    while len(previous_round_match_nos) > 1:
        current_round_match_nos: list[int] = []
        next_round_match_count = math.ceil(
            len(previous_round_match_nos) / max_players
        )
        source_chunks = chunked_evenly(
            previous_round_match_nos, next_round_match_count
        )
        # Every heat of the round sends the same number of players on.
        qualifiers_per_heat = max(
            1, max_players // max(len(chunk) for chunk in source_chunks)
        )
        for source_chunk in source_chunks:
            specs.append(
                MatchSpec(
                    round_no=round_no,
                    match_no=match_no,
                    state='pending',
                    slots=_build_ffa_qualifier_slots(
                        source_chunk, qualifiers_per_heat
                    ),
                )
            )
            current_round_match_nos.append(match_no)
            match_no += 1

        previous_round_match_nos = current_round_match_nos
        round_no += 1

    return specs


def _build_ffa_qualifier_slots(
    source_chunk: list[int], qualifiers_per_heat: int
) -> list[SlotSpec]:
    slots: list[SlotSpec] = []
    slot_no = 1
    for source_match_no in source_chunk:
        for _ in range(qualifiers_per_heat):
            slots.append(
                SlotSpec(
                    slot_no=slot_no,
                    participant_id=None,
                    source_match_no=source_match_no,
                )
            )
            slot_no += 1
    return slots


def build_flatout2_follow_up_specs(
    previous_round_match_nos: list[int],
    *,
    first_match_no: int,
    max_players: int,
    qualifier_count_per_match: int,
) -> list[MatchSpec]:
    specs: list[MatchSpec] = []
    match_no = first_match_no
    round_no = 2
    while len(previous_round_match_nos) > 1:
        source_entries = [
            source_match_no
            for source_match_no in previous_round_match_nos
            for _ in range(qualifier_count_per_match)
        ]
        next_round_match_count = math.ceil(len(source_entries) / max_players)
        current_round_match_nos: list[int] = []

        for source_chunk in chunked_evenly(
            source_entries, next_round_match_count
        ):
            slots = [
                SlotSpec(
                    slot_no=index + 1,
                    participant_id=None,
                    source_match_no=source_match_no,
                )
                for index, source_match_no in enumerate(source_chunk)
            ]

            specs.append(
                MatchSpec(
                    round_no=round_no,
                    match_no=match_no,
                    state='pending',
                    slots=slots,
                )
            )
            current_round_match_nos.append(match_no)
            match_no += 1

        previous_round_match_nos = current_round_match_nos
        round_no += 1

    return specs

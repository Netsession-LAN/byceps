"""
byceps.services.netsession_tourney.swiss_pairing_groups
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Pairing of the participants within one Swiss record group.
"""

from __future__ import annotations

from collections import defaultdict

from .models import (
    Participant,
    ParticipantID,
)
from .swiss_pairing_records import (
    _SwissRecords,
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

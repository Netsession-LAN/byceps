"""
byceps.services.netsession_tourney.engines.engine_pairings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Pure helpers that build the match specs of Swiss and round robin stages
by rotating the participants (circle method).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.models import ParticipantID

from .base import MatchSpec
from .bracket_helpers import seeded_slots


def build_swiss_specs(
    participant_ids: list[ParticipantID], round_count: int
) -> list[MatchSpec]:
    rotating = _with_bye_placeholder(participant_ids)

    specs: list[MatchSpec] = []
    match_no = 1
    for round_no in range(1, round_count + 1):
        round_specs = _build_swiss_round_specs(rotating, round_no, match_no)
        specs.extend(round_specs)
        match_no += len(round_specs)

        # Minimal deterministic re-pairing so byes are not stuck on
        # the same participant every round in odd-sized fields.
        if len(rotating) > 2:
            rotating = _rotate(rotating)

    return specs


def _build_swiss_round_specs(
    rotating: list[ParticipantID | None], round_no: int, first_match_no: int
) -> list[MatchSpec]:
    specs: list[MatchSpec] = []
    for index in range(0, len(rotating), 2):
        p1 = rotating[index]
        p2 = rotating[index + 1]
        state = 'ready' if p1 and p2 else 'pending'
        specs.append(
            MatchSpec(
                round_no=round_no,
                match_no=first_match_no + len(specs),
                state=state,
                slots=seeded_slots(p1, p2),
            )
        )
    return specs


def build_round_robin_specs(
    participant_ids: list[ParticipantID],
    *,
    round_count: int,
    first_match_no: int,
) -> tuple[list[MatchSpec], int]:
    rotating = _with_bye_placeholder(participant_ids)

    pair_count = len(rotating) // 2
    specs: list[MatchSpec] = []
    match_no = first_match_no

    for round_no in range(1, round_count + 1):
        round_specs = _build_round_robin_round_specs(
            rotating, pair_count, round_no, match_no
        )
        specs.extend(round_specs)
        match_no += len(round_specs)

        rotating = _rotate(rotating)

    return specs, match_no


def _build_round_robin_round_specs(
    rotating: list[ParticipantID | None],
    pair_count: int,
    round_no: int,
    first_match_no: int,
) -> list[MatchSpec]:
    specs: list[MatchSpec] = []
    for index in range(pair_count):
        pair = _get_round_robin_pair(rotating, index)
        if pair is None:
            continue

        p1, p2 = pair
        specs.append(
            MatchSpec(
                round_no=round_no,
                match_no=first_match_no + len(specs),
                state='pending' if p2 is None else 'ready',
                slots=seeded_slots(p1, p2),
            )
        )
    return specs


def _get_round_robin_pair(
    rotating: list[ParticipantID | None], index: int
) -> tuple[ParticipantID | None, ParticipantID | None] | None:
    p1 = rotating[index]
    p2 = rotating[-(index + 1)]
    if p1 is None and p2 is None:
        return None

    if p1 is None:
        p1, p2 = p2, p1

    return p1, p2


def _with_bye_placeholder(
    participant_ids: list[ParticipantID],
) -> list[ParticipantID | None]:
    rotating: list[ParticipantID | None] = list(participant_ids)
    if len(rotating) % 2 == 1:
        rotating.append(None)
    return rotating


def _rotate(
    rotating: list[ParticipantID | None],
) -> list[ParticipantID | None]:
    return [rotating[0], rotating[-1], *rotating[1:-1]]

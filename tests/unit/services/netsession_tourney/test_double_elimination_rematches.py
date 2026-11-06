"""Double elimination: losers of the winner bracket are crossed into the
loser bracket, so players rarely meet again early.

Simulated with random winners and a fixed seed (deterministic). Before the
crossing, 8 players met again early in about 75 % of the tournaments,
16 players in about 98 %; some early rematches cannot be avoided by
structure (e.g. two players of the same first-round match in the LB
semifinal of an 8 player bracket).
"""

import random
from uuid import uuid4

import pytest

from byceps.services.netsession_tourney.engines.bracket_helpers import (
    build_double_elimination_specs,
)


def _has_early_loser_bracket_rematch(specs, rng) -> bool:
    by_no = {spec.match_no: spec for spec in specs}
    grand_final_no = max(by_no)
    lb_final_no = by_no[grand_final_no].slots[1].source_match_no

    wb_nos = set()
    for spec in specs:
        if all(
            slot.source_match_no is None
            or (
                slot.source_outcome == 'winner'
                and slot.source_match_no in wb_nos
            )
            for slot in spec.slots
        ):
            wb_nos.add(spec.match_no)

    outcome = {}
    met = set()
    early_rematch = False
    for no in sorted(by_no):
        players = []
        for slot in by_no[no].slots:
            if slot.source_match_no is None:
                players.append(slot.participant_id)
            else:
                winner, loser = outcome[slot.source_match_no]
                players.append(
                    winner if slot.source_outcome == 'winner' else loser
                )
        a, b = players
        pair = frozenset((a, b))
        if (
            pair in met
            and no not in wb_nos
            and no not in (lb_final_no, grand_final_no)
        ):
            early_rematch = True
        met.add(pair)
        winner = a if rng.random() < 0.5 else b
        outcome[no] = (winner, b if winner == a else a)
    return early_rematch


@pytest.mark.parametrize(
    ('player_count', 'max_share'),
    [(4, 0.0), (8, 0.30), (16, 0.45), (32, 0.45), (64, 0.55)],
)
def test_early_loser_bracket_rematches_are_rare(player_count, max_share):
    rng = random.Random(7)
    players = [uuid4() for _ in range(player_count)]
    specs = build_double_elimination_specs(
        players, include_double_grand_final=False
    )

    runs = 2000
    hits = sum(
        _has_early_loser_bracket_rematch(specs, rng) for _ in range(runs)
    )

    assert hits / runs <= max_share

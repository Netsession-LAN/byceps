"""FFA knockouts: every heat of a round sends the same number of players
to the next round (before, e.g. 3/3/2 for three heats and 8 places)."""

from collections import Counter

import pytest

from byceps.services.netsession_tourney.engines.engine_ffa_knockouts import (
    build_ffa_knockout_follow_up_specs,
)


@pytest.mark.parametrize(
    ('heat_count', 'max_players'),
    [(2, 8), (3, 8), (4, 8), (5, 8), (3, 6), (7, 4)],
)
def test_every_heat_qualifies_the_same_number(heat_count, max_players):
    heats = list(range(1, heat_count + 1))

    specs = build_ffa_knockout_follow_up_specs(
        heats, first_match_no=heat_count + 1, max_players=max_players
    )

    first_follow_up_round = [spec for spec in specs if spec.round_no == 2]
    qualifiers = Counter(
        slot.source_match_no
        for spec in first_follow_up_round
        for slot in spec.slots
    )
    assert set(qualifiers) == set(heats)
    assert len(set(qualifiers.values())) == 1
    for spec in first_follow_up_round:
        assert len(spec.slots) <= max_players

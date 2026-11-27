"""
:Copyright: 2026 Kevin Lehmann
:License: Revised BSD (see `LICENSE` file for details)
"""

import pytest

from byceps.services.netsession_tourney.flatout2_builder import (
    summarize_flatout2_builder_rounds,
)


@pytest.mark.parametrize(
    ('participant_count', 'max_players_per_match'),
    [(5, 4), (6, 5), (4, 2), (10, 3)],
)
def test_rounds_end_when_the_field_stops_shrinking(
    participant_count, max_players_per_match
):
    """With at most 5 players per match (3 qualify each), the summary used
    to loop forever."""
    summaries = summarize_flatout2_builder_rounds(
        participant_count=participant_count,
        max_players_per_match=max_players_per_match,
        stop_when_participants_at_most=None,
    )

    assert summaries
    assert len(summaries) <= participant_count


def test_rounds_for_allowed_match_sizes_are_unchanged():
    summaries = summarize_flatout2_builder_rounds(
        participant_count=20,
        max_players_per_match=8,
        stop_when_participants_at_most=None,
    )

    assert summaries == [
        {'round_no': 1, 'match_count': 3, 'max_heat_size': 7},
        {'round_no': 2, 'match_count': 2, 'max_heat_size': 5},
        {'round_no': 3, 'match_count': 1, 'max_heat_size': 6},
    ]

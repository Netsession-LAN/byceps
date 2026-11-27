"""
:Copyright: 2026 Kevin Lehmann
:License: Revised BSD (see `LICENSE` file for details)
"""

from types import SimpleNamespace

import pytest

from byceps.services.netsession_tourney.blueprints.site.match_helpers import (
    _parse_slot_scores,
)


SLOTS = [SimpleNamespace(slot_no=1), SimpleNamespace(slot_no=2)]


@pytest.mark.parametrize('score', ['16:9', ['16', '9'], 3])
def test_scores_that_are_no_mapping_fall_back_to_the_winner(score):
    """A score stored as something other than a mapping used to raise an
    AttributeError on the match pages."""
    result = SimpleNamespace(score=score, winner_slot=1)

    assert _parse_slot_scores(SLOTS, result) == {1: '1', 2: '0'}


def test_display_score_is_still_used():
    result = SimpleNamespace(score={'display': '16:9'}, winner_slot=1)

    assert _parse_slot_scores(SLOTS, result) == {1: '16', 2: '9'}

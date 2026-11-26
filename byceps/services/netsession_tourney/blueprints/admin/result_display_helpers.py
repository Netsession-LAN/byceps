"""
byceps.services.netsession_tourney.blueprints.admin.result_display_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Template helpers for the admin match and participant views.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.match_queries import (
    get_matches_for_tournament,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_participants_for_tournament,
)


def get_dropped_participants(party_id, tournament_id):
    return [
        participant
        for participant in get_participants_for_tournament(
            party_id, tournament_id, include_dropped=True
        )
        if participant.status.value == 'dropped'
    ]


def get_round_neighbours(party_id, tournament_id, match):
    """The previous and next match of the same phase and round (or None)."""
    same_round = _get_same_round_matches(party_id, tournament_id, match)
    ids = [item.id for item in same_round]
    index = ids.index(match.id) if match.id in ids else -1
    if index < 0:
        return None, None
    return _get_neighbours_at(same_round, index)


def _get_same_round_matches(party_id, tournament_id, match) -> list:
    return sorted(
        (
            item
            for item in get_matches_for_tournament(party_id, tournament_id)
            if item.stage_id == match.stage_id
            and item.round_no == match.round_no
        ),
        key=lambda item: item.match_no,
    )


def _get_neighbours_at(same_round: list, index: int) -> tuple:
    previous = same_round[index - 1] if index > 0 else None
    following = same_round[index + 1] if index + 1 < len(same_round) else None
    return previous, following

"""
byceps.services.netsession_tourney.blueprints.site.ranking_duel_state
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Running duel ranking statistics per participant.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict


def new_duel_stats_row(participant) -> dict:
    return {
        'participant': participant,
        'wins': 0,
        'losses': 0,
        'played': 0,
        'match_points': 0,
        'round_wins': 0,
        'round_losses': 0,
        'round_diff': 0,
        'buchholz': 0,
        'opponent_wl_sum': 0,
        'second_order_sos': 0,
    }


class DuelRankingState:
    def __init__(self, participants) -> None:
        self.stats_by_participant_id = {
            participant.id: new_duel_stats_row(participant)
            for participant in participants
        }
        self.head_to_head_winner_id_by_pair = {}
        self.opponent_ids_by_participant_id = defaultdict(list)

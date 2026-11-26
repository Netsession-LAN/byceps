"""Netsession: ranking rows filled from match results."""

from datetime import datetime
from types import SimpleNamespace

from byceps.services.netsession_tourney.stage_ranking_rows import (
    new_ranking_row,
    RankingTally,
)


def _participant(seed):
    return SimpleNamespace(seed=seed, created_at=datetime(2026, 1, 1))


def _slots(*participant_ids):
    return [
        SimpleNamespace(slot_no=no, participant_id=pid)
        for no, pid in enumerate(participant_ids, start=1)
    ]


def _result(winner_slot, score=None, ranking=None):
    return SimpleNamespace(
        winner_slot=winner_slot,
        score_json=score or {},
        ranking_json=ranking or {},
    )


def _tally(*ids, ffa=False, swiss=False, points_per_kill=0):
    return RankingTally(
        rows_by_participant_id={
            pid: new_ranking_row(_participant(1)) for pid in ids
        },
        is_ffa_scoring_stage=ffa,
        is_swiss_stage=swiss,
        points_per_kill=points_per_kill,
    )


def test_duel_counts_wins_points_and_rounds():
    tally = _tally('a', 'b')

    tally.add_result(_result(1, {'slots': {'1': 13, '2': 7}}), _slots('a', 'b'))

    a, b = tally.rows_by_participant_id['a'], tally.rows_by_participant_id['b']
    assert (a['wins'], a['match_points'], a['round_diff']) == (1, 3, 6)
    assert (b['losses'], b['round_wins'], b['round_losses']) == (1, 7, 13)
    assert tally.head_to_head_winner_id_by_pair[frozenset({'a', 'b'})] == 'a'
    assert tally.opponent_ids_by_participant_id['a'] == ['b']


def test_swiss_walkover_counts_the_win_but_no_pairing_or_rounds():
    tally = _tally('a', 'b', swiss=True)

    tally.add_result(_result(1, {'walkover': True}), _slots('a', 'b'))

    a = tally.rows_by_participant_id['a']
    assert a['wins'] == 1
    assert a['round_wins'] == 0
    assert tally.head_to_head_winner_id_by_pair == {}
    assert tally.opponent_ids_by_participant_id['a'] == []  # defaultdict


def test_bye_gives_no_win():
    tally = _tally('a')

    tally.add_result(_result(1), _slots('a', None))

    assert tally.rows_by_participant_id['a']['wins'] == 0


def test_ffa_adds_points_kills_and_best_placement():
    tally = _tally('a', 'b', ffa=True, points_per_kill=2)
    ranking = {'placements': {'1': 3, '2': 1}, 'points': {'1': 5, 2: 10}}

    tally.add_result(
        _result(None, {'slots': {'1': 4, '2': 'x'}}, ranking), _slots('a', 'b')
    )
    tally.add_result(
        _result(None, {}, {'placements': {'1': 2}}), _slots('a', 'b')
    )

    a, b = tally.rows_by_participant_id['a'], tally.rows_by_participant_id['b']
    assert (a['points'], a['kills'], a['total_points'], a['placement']) == (
        5,
        4,
        13,
        2,
    )
    assert (b['points'], b['kills'], b['total_points'], b['placement']) == (
        10,
        0,
        10,
        1,
    )


def test_strength_of_schedule():
    tally = _tally('a', 'b', 'c')
    tally.add_result(_result(1), _slots('a', 'b'))
    tally.add_result(_result(1), _slots('b', 'c'))

    tally.add_strength_of_schedule()

    rows = tally.rows_by_participant_id
    assert rows['a']['buchholz'] == 1  # b won once
    assert rows['b']['opponent_wl_sum'] == (1 - 0) + (0 - 1)
    assert rows['c']['second_order_sos'] == rows['b']['opponent_wl_sum']

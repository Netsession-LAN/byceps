"""Netsession: groups of a round robin groups stage on the bracket page."""

from types import SimpleNamespace

import pytest

from byceps.services.netsession_tourney.blueprints.site.round_robin_groups_display import (
    _assign_groups,
    _group_letter,
    add_round_robin_groups,
)
from byceps.services.netsession_tourney.models import StageType


def _row(match_no, *participant_ids):
    match = SimpleNamespace(id=f'm{match_no}', match_no=match_no, stage_id='s')
    slots = [
        SimpleNamespace(slot_no=index, participant_id=participant_id)
        for index, participant_id in enumerate(participant_ids, start=1)
    ]
    return {'match': match}, slots


def _rows_and_slots(*specs):
    rows, slots_by_match_id = [], {}
    for spec in specs:
        row, slots = _row(*spec)
        rows.append(row)
        slots_by_match_id[row['match'].id] = slots
    return rows, slots_by_match_id


def test_participants_who_meet_share_a_group():
    rows, slots = _rows_and_slots(
        (1, 'a', 'b'),
        (2, 'c', 'd'),
        (3, 'a', 'e'),  # e joins a's group
        (4, 'd', None),  # bye
        (5, 'b', 'e'),
    )

    groups = _assign_groups(rows, slots)

    assert groups == {'a': 0, 'b': 0, 'e': 0, 'c': 1, 'd': 1}


def test_groups_are_numbered_by_first_match():
    rows, slots = _rows_and_slots((2, 'x', 'y'), (1, 'p', 'q'))

    groups = _assign_groups(rows, slots)

    assert groups['p'] == 0
    assert groups['x'] == 1


@pytest.mark.parametrize(
    ('index', 'expected'), [(0, 'A'), (1, 'B'), (25, 'Z'), (26, 'AA')]
)
def test_group_letters(index, expected):
    assert _group_letter(index) == expected


def test_other_stage_types_are_left_alone():
    rows, slots = _rows_and_slots((1, 'a', 'b'), (2, 'c', 'd'))
    sections = [{'rounds': [{'rows': rows}]}]
    stages_by_id = {'s': SimpleNamespace(type=StageType.league)}

    add_round_robin_groups(sections, stages_by_id, slots, {}, {})

    assert 'groups' not in sections[0]

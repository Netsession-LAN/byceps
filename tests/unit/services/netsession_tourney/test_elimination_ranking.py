"""Netsession: final placements for elimination brackets."""

from types import SimpleNamespace as NS

from byceps.services.netsession_tourney.blueprints.site.elimination_ranking import (
    apply_placements,
    build_elimination_placements,
)


class Bracket:
    """Tiny builder for match graphs: slots reference source matches."""

    def __init__(self):
        self.matches = []
        self.slots = {}
        self.results = {}

    def match(self, match_id, *slots):
        """Each slot: participant ID, or ('winner'|'loser', source match ID)."""
        self.matches.append(NS(id=match_id))
        self.slots[match_id] = []
        for slot_no, spec in enumerate(slots, start=1):
            if isinstance(spec, tuple):
                outcome, source = spec
                source_slot_id = f'{source}-1'
                participant_id = None
            else:
                outcome, source_slot_id, participant_id = 'winner', None, spec
            self.slots[match_id].append(
                NS(
                    id=f'{match_id}-{slot_no}',
                    slot_no=slot_no,
                    participant_id=participant_id,
                    source_match_slot_id=source_slot_id,
                    source_outcome=outcome,
                )
            )

    def win(self, match_id, winner, loser, *, skipped=False):
        """Record a result and propagate participants into target slots."""
        slots = self.slots[match_id]
        for slot, participant in zip(slots, (winner, loser), strict=False):
            if slot.participant_id is None:
                slot.participant_id = participant
        winner_slot = next(s.slot_no for s in slots if s.participant_id == winner)
        score = {'grand_final_reset_skipped': True} if skipped else {}
        self.results[match_id] = NS(winner_slot=None if skipped else winner_slot, score=score)
        for other_slots in self.slots.values():
            for slot in other_slots:
                if slot.source_match_slot_id == f'{match_id}-1':
                    slot.participant_id = (
                        winner if slot.source_outcome == 'winner' else loser
                    )

    def places(self):
        return build_elimination_placements(
            self.matches, self.slots, self.results
        )


def test_single_elimination_with_third_place_match():
    b = Bracket()
    b.match('m1', 'p1', 'p4')
    b.match('m2', 'p2', 'p3')
    b.match('final', ('winner', 'm1'), ('winner', 'm2'))
    b.match('third', ('loser', 'm1'), ('loser', 'm2'))
    b.win('m1', 'p1', 'p4')
    b.win('m2', 'p3', 'p2')
    b.win('final', 'p3', 'p1')
    b.win('third', 'p4', 'p2')

    assert b.places() == {'p3': 1, 'p1': 2, 'p4': 3, 'p2': 4}


def test_single_elimination_without_third_place_shares_place_3():
    b = Bracket()
    b.match('m1', 'p1', 'p4')
    b.match('m2', 'p2', 'p3')
    b.match('final', ('winner', 'm1'), ('winner', 'm2'))
    b.win('m1', 'p1', 'p4')
    b.win('m2', 'p2', 'p3')
    b.win('final', 'p2', 'p1')

    assert b.places() == {'p2': 1, 'p1': 2, 'p4': 3, 'p3': 3}


def _double_elimination():
    b = Bracket()
    b.match('wb1', 'p1', 'p4')
    b.match('wb2', 'p2', 'p3')
    b.match('wbf', ('winner', 'wb1'), ('winner', 'wb2'))
    b.match('lb1', ('loser', 'wb1'), ('loser', 'wb2'))
    b.match('lbf', ('winner', 'lb1'), ('loser', 'wbf'))
    b.match('gf', ('winner', 'wbf'), ('winner', 'lbf'))
    b.win('wb1', 'p1', 'p4')
    b.win('wb2', 'p2', 'p3')
    b.win('wbf', 'p1', 'p2')
    b.win('lb1', 'p3', 'p4')
    b.win('lbf', 'p2', 'p3')
    return b


def test_double_elimination():
    b = _double_elimination()
    b.win('gf', 'p1', 'p2')

    assert b.places() == {'p1': 1, 'p2': 2, 'p3': 3, 'p4': 4}


def test_double_grand_final_reset_played():
    b = _double_elimination()
    b.match('gf2', ('winner', 'gf'), ('loser', 'gf'))
    b.win('gf', 'p2', 'p1')
    b.win('gf2', 'p2', 'p1')

    assert b.places() == {'p2': 1, 'p1': 2, 'p3': 3, 'p4': 4}


def test_double_grand_final_reset_skipped():
    b = _double_elimination()
    b.match('gf2', ('winner', 'gf'), ('loser', 'gf'))
    b.win('gf', 'p1', 'p2')
    b.win('gf2', 'p1', 'p2', skipped=True)

    assert b.places() == {'p1': 1, 'p2': 2, 'p3': 3, 'p4': 4}


def test_unfinished_bracket_has_no_placements():
    b = Bracket()
    b.match('m1', 'p1', 'p2')
    b.match('m2', 'p3', 'p4')
    b.match('final', ('winner', 'm1'), ('winner', 'm2'))
    b.win('m1', 'p1', 'p2')

    assert b.places() is None


def test_apply_placements_orders_rows_and_appends_unplaced():
    rows = [
        {'rank': 1, 'participant': NS(id='p2')},
        {'rank': 2, 'participant': NS(id='p1')},
        {'rank': 3, 'participant': NS(id='x')},
    ]

    result = apply_placements(rows, {'p1': 1, 'p2': 2})

    assert [(r['participant'].id, r['rank']) for r in result] == [
        ('p1', 1),
        ('p2', 2),
        ('x', 3),
    ]

"""
byceps.services.netsession_tourney.blueprints.site.double_elimination_brackets
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Assign the matches of a double elimination stage to the winner,
loser and grand final brackets.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations


_BRACKET_BY_SOURCE_BRACKETS = {
    frozenset({'WB'}): 'WB',
    frozenset({'LB'}): 'LB',
    frozenset({'WB', 'LB'}): 'GF',
}


def _assign_double_elimination_brackets(
    sorted_matches, incoming_by_match_id, stage_match_ids
) -> dict:
    bracket_by_match_id = {}

    changed = True
    while changed:
        changed = False
        for match in sorted_matches:
            incoming = _get_stage_incoming(
                match, incoming_by_match_id, stage_match_ids
            )
            bracket = bracket_by_match_id.get(match.id)
            next_bracket = _determine_bracket(
                bracket, incoming, bracket_by_match_id
            )
            if next_bracket != bracket:
                bracket_by_match_id[match.id] = next_bracket
                changed = True

    return bracket_by_match_id


def _get_stage_incoming(match, incoming_by_match_id, stage_match_ids) -> list:
    return [
        (source_match_id, outcome)
        for source_match_id, outcome in incoming_by_match_id.get(match.id, [])
        if source_match_id in stage_match_ids
    ]


def _determine_bracket(bracket, incoming, bracket_by_match_id):
    if not incoming:
        return 'WB'

    source_brackets = {
        bracket_by_match_id.get(source_match_id)
        for source_match_id, _ in incoming
    }
    source_brackets.discard(None)

    if 'GF' in source_brackets:
        return 'GF'
    if any(is_loser_outcome(outcome) for _, outcome in incoming):
        return 'LB'
    return _BRACKET_BY_SOURCE_BRACKETS.get(frozenset(source_brackets), bracket)


def is_loser_outcome(outcome) -> bool:
    value = getattr(outcome, 'value', outcome)
    return value == 'loser'

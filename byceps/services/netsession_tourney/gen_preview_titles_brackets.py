"""
byceps.services.netsession_tourney.gen_preview_titles_brackets
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Assignment of the double elimination preview matches to their
brackets (winner, loser, grand final).
"""

from __future__ import annotations

from typing import Any

from .double_grand_final import (
    is_loser_source_outcome,
)
from .engines.base import MatchSpec


def _assign_generation_preview_brackets(
    specs_by_match_no: dict[int, MatchSpec],
) -> dict[int, str]:
    bracket_by_match_no: dict[int, str] = {}

    changed = True
    while changed:
        changed = False
        for spec in specs_by_match_no.values():
            incoming = [
                (slot.source_match_no, slot.source_outcome)
                for slot in spec.slots
                if slot.source_match_no is not None
            ]
            bracket = bracket_by_match_no.get(spec.match_no)
            next_bracket = bracket
            if not incoming:
                next_bracket = 'WB'
            else:
                next_bracket = _derive_generation_preview_bracket(
                    incoming, bracket_by_match_no, next_bracket
                )

            if next_bracket != bracket:
                bracket_by_match_no[spec.match_no] = next_bracket
                changed = True

    return bracket_by_match_no


_BRACKET_BY_SOURCE_BRACKETS = {
    frozenset({'WB'}): 'WB',
    frozenset({'LB'}): 'LB',
    frozenset({'WB', 'LB'}): 'GF',
}


def _derive_generation_preview_bracket(
    incoming: list[tuple[int, Any]],
    bracket_by_match_no: dict[int, str],
    current_bracket: str | None,
) -> str | None:
    source_brackets = {
        bracket_by_match_no.get(source_match_no)
        for source_match_no, _ in incoming
    }
    source_brackets.discard(None)

    if 'GF' in source_brackets:
        return 'GF'
    if any(is_loser_source_outcome(outcome) for _, outcome in incoming):
        return 'LB'
    return _BRACKET_BY_SOURCE_BRACKETS.get(
        frozenset(source_brackets), current_bracket
    )

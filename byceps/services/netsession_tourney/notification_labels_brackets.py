"""
byceps.services.netsession_tourney.notification_labels_brackets
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Assignment of double elimination matches to their brackets for the
notification labels.
"""

from __future__ import annotations

from typing import Any

from .dbmodels import (
    DbNetsessionTourneyMatch,
)
from .models import (
    MatchID,
)


def _assign_double_elimination_notification_brackets(
    sorted_matches: list[DbNetsessionTourneyMatch],
    stage_match_ids: set[MatchID],
    incoming_by_match_id: dict[MatchID, list[tuple[MatchID, Any]]],
) -> dict[MatchID, str]:
    """Assign 'WB', 'LB' or 'GF' to each match, iterating until stable."""
    bracket_by_match_id: dict[MatchID, str] = {}

    changed = True
    while changed:
        changed = False
        for match in sorted_matches:
            incoming = _get_stage_incoming_notification_matches(
                match.id, incoming_by_match_id, stage_match_ids
            )
            bracket = bracket_by_match_id.get(match.id)
            next_bracket = _resolve_next_notification_bracket(
                incoming, bracket_by_match_id, bracket
            )

            if next_bracket != bracket:
                bracket_by_match_id[match.id] = next_bracket
                changed = True

    return bracket_by_match_id


def _get_stage_incoming_notification_matches(
    match_id: MatchID,
    incoming_by_match_id: dict[MatchID, list[tuple[MatchID, Any]]],
    stage_match_ids: set[MatchID],
) -> list[tuple[MatchID, Any]]:
    return [
        (source_match_id, outcome)
        for source_match_id, outcome in incoming_by_match_id.get(match_id, [])
        if source_match_id in stage_match_ids
    ]


def _resolve_next_notification_bracket(
    incoming: list[tuple[MatchID, Any]],
    bracket_by_match_id: dict[MatchID, str],
    bracket: str | None,
) -> str | None:
    next_bracket = (
        _determine_next_notification_bracket(incoming, bracket_by_match_id)
        if incoming
        else 'WB'
    )
    if next_bracket is None:
        next_bracket = bracket
    return next_bracket


_NOTIFICATION_BRACKET_BY_SOURCE_BRACKETS = {
    frozenset({'WB'}): 'WB',
    frozenset({'LB'}): 'LB',
    frozenset({'WB', 'LB'}): 'GF',
}


def _determine_next_notification_bracket(
    incoming: list[tuple[MatchID, Any]],
    bracket_by_match_id: dict[MatchID, str],
) -> str | None:
    """Return the bracket derived from the incoming matches, or `None`
    if it cannot be derived (yet)."""
    source_brackets = {
        bracket_by_match_id.get(source_match_id)
        for source_match_id, _ in incoming
    }
    source_brackets.discard(None)

    if 'GF' in source_brackets:
        return 'GF'
    if any(_is_loser_notification_outcome(outcome) for _, outcome in incoming):
        return 'LB'
    return _NOTIFICATION_BRACKET_BY_SOURCE_BRACKETS.get(
        frozenset(source_brackets)
    )


def _is_loser_notification_outcome(outcome: Any) -> bool:
    value = getattr(outcome, 'value', outcome)
    return value == 'loser'

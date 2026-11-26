"""
byceps.services.netsession_tourney.gen_preview_titles_flatout2
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Round display titles of the FlatOut 2 generation preview.
"""

from __future__ import annotations

from typing import Any

from .engines.base import MatchSpec
from .models import (
    Stage,
)


def _build_flatout2_generation_preview_round_titles(
    stage: Stage,
    match_specs: list[MatchSpec],
) -> dict[int, str]:
    titles_by_round_no = _get_configured_flatout2_round_titles(stage)
    if titles_by_round_no:
        return titles_by_round_no

    round_nos = sorted({spec.round_no for spec in match_specs})
    total_round_count = _get_flatout2_total_round_count(stage)

    return {
        round_no: _get_flatout2_generation_preview_round_title(
            round_no, total_round_count
        )
        for round_no in round_nos
    }


def _get_configured_flatout2_round_titles(stage: Stage) -> dict[int, str]:
    raw_rounds = (stage.settings or {}).get('flatout2_rounds')
    if not isinstance(raw_rounds, list):
        return {}

    return _parse_flatout2_round_display_titles(raw_rounds)


def _get_flatout2_total_round_count(stage: Stage) -> int:
    try:
        return int((stage.settings or {}).get('round_count') or 0)
    except TypeError, ValueError:
        return 0


def _get_flatout2_generation_preview_round_title(
    round_no: int, total_round_count: int
) -> str:
    if total_round_count > 0 and round_no == total_round_count:
        return 'Finale'
    return f'Runde {round_no}'


def _parse_flatout2_round_display_titles(
    raw_rounds: list[Any],
) -> dict[int, str]:
    titles_by_round_no: dict[int, str] = {}
    for raw_round in raw_rounds:
        if not isinstance(raw_round, dict):
            continue
        round_no_and_title = _parse_flatout2_round_display_title(raw_round)
        if round_no_and_title is not None:
            round_no, display_title = round_no_and_title
            titles_by_round_no[round_no] = display_title
    return titles_by_round_no


def _parse_flatout2_round_display_title(
    raw_round: dict[str, Any],
) -> tuple[int, str] | None:
    """Return round number and display title of a configured round, or
    `None` if it has no valid round number or no title."""
    round_no = _parse_flatout2_round_no(raw_round)
    if round_no is None:
        return None

    display_title = str(
        raw_round.get('display_title') or raw_round.get('title') or ''
    ).strip()
    if not display_title:
        return None

    return round_no, display_title


def _parse_flatout2_round_no(raw_round: dict[str, Any]) -> int | None:
    try:
        round_no = int(raw_round.get('round_no') or 0)
    except TypeError, ValueError:
        return None

    if round_no < 1:
        return None

    return round_no

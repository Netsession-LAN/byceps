"""
byceps.services.netsession_tourney.blueprints.site.flatout2_round_summary_parsing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Parse the expected FlatOut 2 rounds from explicit round settings and
from builder round summaries.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from .ffa_single_elimination_rendering import (
    get_ffa_single_elimination_round_title,
)


def _parse_explicit_round_numbers(
    settings, raw_round: dict, index: int
) -> tuple[int, int, int] | None:
    try:
        round_no = int(raw_round.get('round_no') or index)
        match_count = int(raw_round.get('match_count') or 0)
        max_heat_size = int(settings.get('max_players_per_match') or 0)
    except TypeError, ValueError:
        return None

    return round_no, match_count, max_heat_size


def _build_explicit_round_display_title(
    raw_round: dict, index: int, total_round_count: int, round_no: int
) -> str:
    return str(
        raw_round.get('display_title')
        or raw_round.get('title')
        or ('Finale' if index == total_round_count else f'Runde {round_no}')
    ).strip()


def _parse_explicit_round(
    settings, raw_round, index: int, total_round_count: int
) -> dict[str, int | str] | None:
    if not isinstance(raw_round, dict):
        return None

    numbers = _parse_explicit_round_numbers(settings, raw_round, index)
    if numbers is None:
        return None

    round_no, match_count, max_heat_size = numbers
    if round_no < 1 or match_count < 1 or max_heat_size < 1:
        return None

    return {
        'round_no': round_no,
        'match_count': match_count,
        'max_heat_size': max_heat_size,
        'display_title': _build_explicit_round_display_title(
            raw_round, index, total_round_count, round_no
        ),
    }


def _parse_explicit_rounds(settings) -> list[dict[str, int | str]]:
    raw_rounds = settings.get('flatout2_rounds')
    if not isinstance(raw_rounds, list):
        return []

    parsed_rounds = []
    total_round_count = len(raw_rounds)
    for index, raw_round in enumerate(raw_rounds, start=1):
        parsed_round = _parse_explicit_round(
            settings, raw_round, index, total_round_count
        )
        if parsed_round is not None:
            parsed_rounds.append(parsed_round)

    return parsed_rounds


def _parse_builder_round_summary_numbers(
    settings, raw_round_summary: dict, index: int
) -> tuple[int, int, int] | None:
    try:
        round_no = int(raw_round_summary.get('round_no') or index)
        match_count = int(raw_round_summary.get('match_count') or 0)
        max_heat_size = int(
            raw_round_summary.get('max_heat_size')
            or settings.get('max_players_per_match')
            or 0
        )
    except TypeError, ValueError:
        return None

    return round_no, match_count, max_heat_size


def _parse_builder_round_summary(
    stage, settings, raw_round_summary, index: int, total_round_count: int
) -> dict[str, int | str] | None:
    if not isinstance(raw_round_summary, dict):
        return None

    numbers = _parse_builder_round_summary_numbers(
        settings, raw_round_summary, index
    )
    if numbers is None:
        return None

    round_no, match_count, max_heat_size = numbers
    if match_count < 1:
        return None

    return {
        'round_no': round_no,
        'match_count': match_count,
        'max_heat_size': max_heat_size,
        'display_title': get_ffa_single_elimination_round_title(
            index - 1,
            total_round_count,
            stage_type=stage.type,
            round_no=round_no,
            total_round_count=total_round_count,
        ),
    }


def _parse_builder_round_summaries(
    stage, settings
) -> list[dict[str, int | str]]:
    raw_round_summaries = settings.get('builder_expected_round_summaries')
    if not isinstance(raw_round_summaries, list):
        return []

    parsed_round_summaries = []
    total_round_count = len(raw_round_summaries)
    for index, raw_round_summary in enumerate(raw_round_summaries, start=1):
        parsed_round_summary = _parse_builder_round_summary(
            stage, settings, raw_round_summary, index, total_round_count
        )
        if parsed_round_summary is not None:
            parsed_round_summaries.append(parsed_round_summary)

    return parsed_round_summaries

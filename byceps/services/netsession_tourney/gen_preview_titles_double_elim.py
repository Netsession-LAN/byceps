"""
byceps.services.netsession_tourney.gen_preview_titles_double_elim
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Round display titles of the double elimination generation preview.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from .engines.base import MatchSpec
from .gen_preview_titles_brackets import (
    _assign_generation_preview_brackets,
)


def _build_double_elimination_generation_preview_round_titles(
    match_specs: list[MatchSpec],
) -> dict[int, str]:
    specs_by_match_no = {
        spec.match_no: spec
        for spec in sorted(
            match_specs, key=lambda item: (item.round_no, item.match_no)
        )
    }
    bracket_by_match_no = _assign_generation_preview_brackets(specs_by_match_no)

    round_nos_by_bracket, brackets_by_round_no = (
        _group_generation_preview_round_nos(
            specs_by_match_no, bracket_by_match_no
        )
    )

    wb_titles = _build_generation_preview_bracket_round_titles(
        round_nos_by_bracket['WB'], _get_generation_preview_winner_round_title
    )
    lb_titles = _build_generation_preview_bracket_round_titles(
        round_nos_by_bracket['LB'], _get_generation_preview_loser_round_title
    )
    gf_titles = _build_generation_preview_grand_final_titles(
        round_nos_by_bracket['GF']
    )

    return _join_generation_preview_round_titles(
        brackets_by_round_no, [wb_titles, lb_titles, gf_titles]
    )


def _group_generation_preview_round_nos(
    specs_by_match_no: dict[int, MatchSpec],
    bracket_by_match_no: dict[int, str],
) -> tuple[dict[str, list[int]], dict[int, set[str]]]:
    """Return the round numbers per bracket (in order of appearance) and
    the brackets per round number."""
    round_nos_by_bracket: dict[str, list[int]] = defaultdict(list)
    brackets_by_round_no: dict[int, set[str]] = defaultdict(set)
    for spec in specs_by_match_no.values():
        bracket = bracket_by_match_no.get(spec.match_no)
        if bracket is None:
            continue
        if spec.round_no not in round_nos_by_bracket[bracket]:
            round_nos_by_bracket[bracket].append(spec.round_no)
        brackets_by_round_no[spec.round_no].add(bracket)

    return round_nos_by_bracket, brackets_by_round_no


def _build_generation_preview_bracket_round_titles(
    round_nos: list[int], get_round_title: Callable[[int, int], str]
) -> dict[int, str]:
    return {
        round_no: get_round_title(index, len(round_nos))
        for index, round_no in enumerate(sorted(round_nos))
    }


def _join_generation_preview_round_titles(
    brackets_by_round_no: dict[int, set[str]],
    titles_by_bracket: list[dict[int, str]],
) -> dict[int, str]:
    title_by_round_no: dict[int, str] = {}
    for round_no in sorted(brackets_by_round_no):
        parts = [
            titles[round_no]
            for titles in titles_by_bracket
            if round_no in titles
        ]
        if parts:
            title_by_round_no[round_no] = ' + '.join(parts)

    return title_by_round_no


def _build_generation_preview_grand_final_titles(
    gf_round_nos: list[int],
) -> dict[int, str]:
    gf_titles = {}
    sorted_gf_round_nos = sorted(gf_round_nos)
    for index, round_no in enumerate(sorted_gf_round_nos):
        gf_titles[round_no] = (
            'Grand Final'
            if index == 0
            else 'Double Grand Final'
            if index == 1
            else f'Grand Final {index + 1}'
        )
    return gf_titles


def _get_generation_preview_winner_round_title(
    round_index: int, round_count: int
) -> str:
    if round_count <= 1 or round_index == round_count - 1:
        return 'Winner Bracket Final'
    if round_index == round_count - 2:
        return 'Winner Bracket Semi-Final'
    return f'Winner Bracket Round {round_index + 1}'


def _get_generation_preview_loser_round_title(
    round_index: int, round_count: int
) -> str:
    if round_count <= 1 or round_index == round_count - 1:
        return 'Loser Bracket Final'
    if round_count >= 3 and round_index == round_count - 2:
        return 'Loser Bracket Semi-Final'
    return f'Loser Bracket Round {round_index + 1}'

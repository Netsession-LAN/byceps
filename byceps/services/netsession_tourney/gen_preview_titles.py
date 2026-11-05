"""
byceps.services.netsession_tourney.gen_preview_titles
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Round display titles for the match generation preview of a stage
(builder title, FlatOut 2 rounds, double elimination brackets).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .double_grand_final import (
    _is_loser_source_outcome,
)
from .engines.base import MatchSpec
from .models import (
    Stage,
    StageType,
)


def _build_generation_preview_round_titles_by_round_no(
    stage: Stage,
    match_specs: list[MatchSpec],
) -> dict[int, str]:
    builder_display_title = str(
        (stage.settings or {}).get('builder_display_title') or ''
    ).strip()
    if builder_display_title:
        round_nos = sorted({spec.round_no for spec in match_specs})
        return {round_no: builder_display_title for round_no in round_nos}

    if stage.type == StageType.ffa_flatout2_single_elimination:
        return _build_flatout2_generation_preview_round_titles(
            stage, match_specs
        )

    if stage.type not in {
        StageType.double_elimination,
        StageType.double_elimination_double_grand_final,
    }:
        return {}

    return _build_double_elimination_generation_preview_round_titles(
        match_specs
    )


def _build_flatout2_generation_preview_round_titles(
    stage: Stage,
    match_specs: list[MatchSpec],
) -> dict[int, str]:
    raw_rounds = (stage.settings or {}).get('flatout2_rounds')
    if isinstance(raw_rounds, list):
        titles_by_round_no = _parse_flatout2_round_display_titles(raw_rounds)
        if titles_by_round_no:
            return titles_by_round_no

    round_nos = sorted({spec.round_no for spec in match_specs})
    try:
        total_round_count = int((stage.settings or {}).get('round_count') or 0)
    except (TypeError, ValueError):
        total_round_count = 0

    return {
        round_no: (
            'Finale'
            if total_round_count > 0 and round_no == total_round_count
            else f'Runde {round_no}'
        )
        for round_no in round_nos
    }


def _parse_flatout2_round_display_titles(
    raw_rounds: list[Any],
) -> dict[int, str]:
    titles_by_round_no: dict[int, str] = {}
    for raw_round in raw_rounds:
        if not isinstance(raw_round, dict):
            continue
        try:
            round_no = int(raw_round.get('round_no') or 0)
        except (TypeError, ValueError):
            continue
        if round_no < 1:
            continue
        display_title = str(
            raw_round.get('display_title') or raw_round.get('title') or ''
        ).strip()
        if display_title:
            titles_by_round_no[round_no] = display_title
    return titles_by_round_no


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

    round_nos_by_bracket: dict[str, list[int]] = defaultdict(list)
    brackets_by_round_no: dict[int, set[str]] = defaultdict(set)
    for spec in specs_by_match_no.values():
        bracket = bracket_by_match_no.get(spec.match_no)
        if bracket is None:
            continue
        if spec.round_no not in round_nos_by_bracket[bracket]:
            round_nos_by_bracket[bracket].append(spec.round_no)
        brackets_by_round_no[spec.round_no].add(bracket)

    wb_titles = {
        round_no: _get_generation_preview_winner_round_title(
            index, len(round_nos_by_bracket['WB'])
        )
        for index, round_no in enumerate(sorted(round_nos_by_bracket['WB']))
    }
    lb_titles = {
        round_no: _get_generation_preview_loser_round_title(
            index, len(round_nos_by_bracket['LB'])
        )
        for index, round_no in enumerate(sorted(round_nos_by_bracket['LB']))
    }
    gf_titles = _build_generation_preview_grand_final_titles(
        round_nos_by_bracket['GF']
    )

    title_by_round_no: dict[int, str] = {}
    for round_no in sorted(brackets_by_round_no):
        parts = []
        if round_no in wb_titles:
            parts.append(wb_titles[round_no])
        if round_no in lb_titles:
            parts.append(lb_titles[round_no])
        if round_no in gf_titles:
            parts.append(gf_titles[round_no])
        if parts:
            title_by_round_no[round_no] = ' + '.join(parts)

    return title_by_round_no


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
    elif any(_is_loser_source_outcome(outcome) for _, outcome in incoming):
        return 'LB'
    elif source_brackets == {'WB'}:
        return 'WB'
    elif source_brackets == {'LB'}:
        return 'LB'
    elif source_brackets == {'WB', 'LB'}:
        return 'GF'
    return current_bracket


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

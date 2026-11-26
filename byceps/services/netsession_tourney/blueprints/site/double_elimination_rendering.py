"""
byceps.services.netsession_tourney.blueprints.site.double_elimination_rendering
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict

from .double_elimination_brackets import (
    _assign_double_elimination_brackets,
    is_loser_outcome as is_loser_outcome,
)
from .double_elimination_sections import (
    build_double_elimination_bracket_sections as build_double_elimination_bracket_sections,
)


def build_double_elimination_match_labels(
    stage_matches,
    incoming_by_match_id,
) -> dict:
    sorted_matches = sorted(
        stage_matches,
        key=lambda match: (match.round_no, match.match_no),
    )
    stage_match_ids = {match.id for match in stage_matches}
    bracket_by_match_id = _assign_double_elimination_brackets(
        sorted_matches, incoming_by_match_id, stage_match_ids
    )

    labels_by_match_id = {
        match.id: f'M #{match.match_no}' for match in stage_matches
    }

    gf_matches = sorted(
        _select_bracket_matches(sorted_matches, bracket_by_match_id, 'GF'),
        key=lambda match: (match.round_no, match.match_no),
    )
    if gf_matches:
        labels_by_match_id.update(_label_grand_final_matches(gf_matches))

    wb_matches = _select_bracket_matches(
        sorted_matches, bracket_by_match_id, 'WB'
    )
    lb_matches = _select_bracket_matches(
        sorted_matches, bracket_by_match_id, 'LB'
    )

    labels_by_match_id.update(
        _label_bracket_matches(
            wb_matches,
            prefix='WB',
            semi_prefix='WB Semi',
            final_label='WB Final',
        )
    )
    labels_by_match_id.update(
        _label_bracket_matches(
            lb_matches,
            prefix='LB',
            semi_prefix='LB Semi',
            final_label='LB Final',
        )
    )

    return labels_by_match_id


def _select_bracket_matches(sorted_matches, bracket_by_match_id, bracket):
    return [
        match
        for match in sorted_matches
        if bracket_by_match_id.get(match.id) == bracket
    ]


def _label_grand_final_matches(gf_matches) -> dict:
    if len(gf_matches) == 1:
        return {gf_matches[0].id: 'Grand Final'}
    if len(gf_matches) == 2:
        return {
            gf_matches[0].id: 'Grand Final',
            gf_matches[1].id: 'Double Grand Final',
        }
    return {
        match.id: f'Grand Final #{index}'
        for index, match in enumerate(gf_matches, start=1)
    }


def is_double_elimination_bracket(bracket, match_labels_by_id) -> bool:
    loser_rounds_present = any(
        label.startswith('LB ')
        for label in _iter_bracket_labels(bracket, match_labels_by_id)
    )
    return loser_rounds_present or any(
        _is_winner_side_label(label)
        for label in _iter_bracket_labels(bracket, match_labels_by_id)
    )


def _iter_bracket_labels(bracket, match_labels_by_id):
    for round_data in bracket:
        for item in round_data['matches']:
            yield match_labels_by_id.get(item['match'].id, '')


def _is_winner_side_label(label: str) -> bool:
    return (
        label.startswith('WB ')
        or label.startswith('Grand Final')
        or label.startswith('Double Grand Final')
    )


def _label_bracket_matches(
    matches,
    *,
    prefix: str,
    semi_prefix: str,
    final_label: str,
) -> dict:
    if not matches:
        return {}

    labels_by_match_id = {}
    matches_by_round_no = defaultdict(list)
    for match in matches:
        matches_by_round_no[match.round_no].append(match)

    sorted_round_nos = sorted(matches_by_round_no.keys())
    final_round_no = sorted_round_nos[-1]
    _label_final_round_matches(
        labels_by_match_id, matches_by_round_no[final_round_no], final_label
    )

    semi_round_no = sorted_round_nos[-2] if len(sorted_round_nos) >= 2 else None
    if semi_round_no is not None:
        _label_semi_round_matches(
            labels_by_match_id, matches_by_round_no[semi_round_no], semi_prefix
        )

    _label_remaining_round_matches(
        labels_by_match_id, matches_by_round_no, sorted_round_nos, prefix
    )

    return labels_by_match_id


def _label_final_round_matches(
    labels_by_match_id: dict, round_matches, final_label: str
) -> None:
    final_round_matches = sorted(
        round_matches, key=lambda match: match.match_no
    )
    for index, match in enumerate(final_round_matches, start=1):
        labels_by_match_id[match.id] = (
            final_label
            if len(final_round_matches) == 1
            else f'{final_label} #{index}'
        )


def _label_semi_round_matches(
    labels_by_match_id: dict, round_matches, semi_prefix: str
) -> None:
    semi_matches = sorted(round_matches, key=lambda match: match.match_no)
    for index, match in enumerate(semi_matches, start=1):
        labels_by_match_id[match.id] = f'{semi_prefix} #{index}'


def _label_remaining_round_matches(
    labels_by_match_id: dict, matches_by_round_no, sorted_round_nos, prefix: str
) -> None:
    running_no = 1
    for round_no in sorted_round_nos:
        for match in sorted(
            matches_by_round_no[round_no],
            key=lambda current_match: current_match.match_no,
        ):
            if match.id in labels_by_match_id:
                continue
            labels_by_match_id[match.id] = f'{prefix} #{running_no}'
            running_no += 1

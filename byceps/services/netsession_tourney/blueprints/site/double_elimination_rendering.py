"""
byceps.services.netsession_tourney.blueprints.site.double_elimination_rendering
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict

from flask_babel import gettext


_BRACKET_BY_SOURCE_BRACKETS = {
    frozenset({'WB'}): 'WB',
    frozenset({'LB'}): 'LB',
    frozenset({'WB', 'LB'}): 'GF',
}


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


def build_double_elimination_bracket_sections(bracket, match_labels_by_id):
    winner_rounds = []
    loser_rounds = []

    for round_data in bracket:
        winner_items = []
        loser_items = []

        for item in round_data['matches']:
            label = match_labels_by_id.get(item['match'].id, '')
            if label.startswith('LB '):
                loser_items.append(item)
            else:
                winner_items.append(item)

        if winner_items:
            winner_rounds.append(
                {'round_no': round_data['round_no'], 'matches': winner_items}
            )
        if loser_items:
            loser_rounds.append(
                {'round_no': round_data['round_no'], 'matches': loser_items}
            )

    _decorate_double_elimination_winner_rounds(
        winner_rounds, match_labels_by_id
    )
    _decorate_double_elimination_loser_rounds(loser_rounds)

    sections = []
    if winner_rounds:
        sections.append(
            {
                'key': 'winner',
                'title': gettext('Winner Bracket'),
                'rounds': winner_rounds,
            }
        )
    sections.append(
        {
            'key': 'loser',
            'title': gettext('Loser Bracket'),
            'rounds': loser_rounds,
        }
    )
    return sections


def _decorate_double_elimination_winner_rounds(
    winner_rounds,
    match_labels_by_id,
) -> None:
    wb_rounds = []
    gf_rounds = []

    for round_data in winner_rounds:
        labels = [
            match_labels_by_id.get(item['match'].id, '')
            for item in round_data['matches']
        ]
        grand_final_title = _get_grand_final_round_title(labels)
        if grand_final_title is not None:
            round_data['display_title'] = grand_final_title
            gf_rounds.append(round_data)
        else:
            wb_rounds.append(round_data)

    for index, round_data in enumerate(wb_rounds):
        round_data['display_round_no'] = str(index + 1)
        round_data['display_title'] = (
            _get_double_elimination_winner_round_title(
                index,
                len(wb_rounds),
            )
        )

    for index, round_data in enumerate(gf_rounds):
        round_data['display_round_no'] = str(len(wb_rounds) + index + 1)


def _get_grand_final_round_title(labels: list[str]) -> str | None:
    if any(label.startswith('Double Grand Final') for label in labels):
        return 'Double Grand Final'
    if any(label.startswith('Grand Final') for label in labels):
        return 'Grand Final'
    return None


def _decorate_double_elimination_loser_rounds(loser_rounds) -> None:
    for index, round_data in enumerate(loser_rounds):
        round_data['display_round_no'] = str(index + 1)
        round_data['display_title'] = _get_double_elimination_loser_round_title(
            index,
            len(loser_rounds),
        )


def _get_double_elimination_winner_round_title(
    round_index: int, round_count: int
) -> str:
    if round_count <= 1 or round_index == round_count - 1:
        return gettext('Winner Bracket Final')
    if round_index == round_count - 2:
        return gettext('Winner Bracket Semi-Final')
    return gettext(
        'Winner Bracket Round %(round_no)s',
        round_no=round_index + 1,
    )


def _get_double_elimination_loser_round_title(
    round_index: int, round_count: int
) -> str:
    if round_count <= 1 or round_index == round_count - 1:
        return gettext('Loser Bracket Final')
    if round_count >= 3 and round_index == round_count - 2:
        return gettext('Loser Bracket Semi-Final')
    return gettext(
        'Loser Bracket Round %(round_no)s',
        round_no=round_index + 1,
    )


def is_loser_outcome(outcome) -> bool:
    value = getattr(outcome, 'value', outcome)
    return value == 'loser'


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

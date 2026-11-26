"""
byceps.services.netsession_tourney.blueprints.site.double_elimination_sections
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Bracket sections and round titles of double elimination stages.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from .double_elimination_brackets import (
    is_loser_outcome as is_loser_outcome,
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

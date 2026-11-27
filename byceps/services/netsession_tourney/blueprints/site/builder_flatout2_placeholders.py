"""
byceps.services.netsession_tourney.blueprints.site.builder_flatout2_placeholders
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Placeholder sections for FlatOut 2 builder stages that are not
materialized yet.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from .flatout2_round_helpers import (
    get_flatout2_expected_round_summaries as _get_flatout2_builder_expected_round_summaries,
)


def _build_flatout2_placeholder_match_sections(stage) -> list[dict]:
    round_summaries = _get_flatout2_builder_expected_round_summaries(stage)
    if not round_summaries:
        return []

    rounds = []
    for round_summary in round_summaries:
        match_count = int(round_summary['match_count'])
        rows = []
        for index in range(1, match_count + 1):
            rows.append(
                {
                    'match': {
                        'id': f'planned-{stage.id}-{round_summary["round_no"]}-{index}',
                    },
                    'match_label': (
                        gettext('Match')
                        if match_count == 1
                        else f'{gettext("Match")} #{index}'
                    ),
                    'participants': [],
                    'participant_count': 0,
                    'slot_capacity': int(round_summary['max_heat_size']),
                    'score_display': gettext('TBA'),
                    'has_result': False,
                    'is_struck': False,
                    'show_kills': False,
                    'host_participant_id': '',
                    'host_name': None,
                    'round_races': [],
                    'is_placeholder': True,
                    'url': None,
                }
            )

        rounds.append(
            {
                'round_no': int(round_summary['round_no']),
                'display_round_no': int(round_summary['round_no']),
                'display_title': str(round_summary['display_title']),
                'time_range_label': None,
                'rows': rows,
            }
        )

    return [
        {
            'key': str(stage.id),
            'title': stage.name,
            'presentation': 'ffa',
            'rounds': rounds,
        }
    ]


def _build_flatout2_placeholder_bracket_sections(stage) -> list[dict]:
    round_summaries = _get_flatout2_builder_expected_round_summaries(stage)
    if not round_summaries:
        return []

    rounds = []
    for round_summary in round_summaries:
        match_count = int(round_summary['match_count'])
        items = []
        for index in range(1, match_count + 1):
            items.append(
                {
                    'match': {
                        'id': f'planned-{stage.id}-{round_summary["round_no"]}-{index}',
                    },
                    'match_label': (
                        gettext('Match')
                        if match_count == 1
                        else f'{gettext("Match")} #{index}'
                    ),
                    'participant_count': 0,
                    'slot_capacity': int(round_summary['max_heat_size']),
                    'source_match_ids': [],
                    'has_result': False,
                    'score_display': gettext('TBA'),
                    'round_match_index': index - 1,
                    'host_name': None,
                    'is_placeholder': True,
                    'url': None,
                }
            )

        rounds.append(
            {
                'round_no': int(round_summary['round_no']),
                'display_round_no': int(round_summary['round_no']),
                'display_title': str(round_summary['display_title']),
                'matches': items,
            }
        )

    return [
        {
            'key': str(stage.id),
            'title': stage.name,
            'presentation': 'ffa',
            'rounds': rounds,
        }
    ]

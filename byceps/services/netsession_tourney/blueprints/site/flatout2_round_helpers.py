"""
byceps.services.netsession_tourney.blueprints.site.flatout2_round_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from .flatout2_round_summary_parsing import (
    _parse_builder_round_summaries,
    _parse_explicit_rounds,
)
from .stage_filters import _is_flatout2_stage


def _parse_materialized_round_numbers(
    settings,
) -> tuple[int, int, int] | None:
    try:
        round_no = int(settings.get('builder_display_round_no') or 1)
        match_count = int(settings.get('builder_expected_match_count') or 0)
        max_heat_size = int(
            settings.get('builder_expected_max_heat_size')
            or settings.get('max_players_per_match')
            or 0
        )
    except TypeError, ValueError:
        return None

    return round_no, match_count, max_heat_size


def _build_materialized_round_summaries(
    settings,
) -> list[dict[str, int | str]]:
    numbers = _parse_materialized_round_numbers(settings)
    if numbers is None:
        return []

    round_no, match_count, max_heat_size = numbers
    if match_count < 1:
        return []

    return [
        {
            'round_no': round_no,
            'match_count': match_count,
            'max_heat_size': max_heat_size,
            'display_title': str(
                settings.get('builder_display_title')
                or gettext('Runde %(round_no)s', round_no=round_no)
            ),
        }
    ]


def get_flatout2_expected_round_summaries(
    stage,
) -> list[dict[str, int | str]]:
    if not _is_flatout2_stage(stage):
        return []

    settings = stage.settings or {}

    parsed_rounds = _parse_explicit_rounds(settings)
    if parsed_rounds:
        return parsed_rounds

    if settings.get('builder_materialized_round_stage'):
        return _build_materialized_round_summaries(settings)

    return _parse_builder_round_summaries(stage, settings)


def build_flatout2_placeholder_match_round(stage, round_summary: dict) -> dict:
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

    return {
        'round_no': int(round_summary['round_no']),
        'display_round_no': int(round_summary['round_no']),
        'display_title': str(round_summary['display_title']),
        'time_range_label': None,
        'rows': rows,
    }


def build_flatout2_placeholder_bracket_round(
    stage, round_summary: dict
) -> dict:
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

    return {
        'round_no': int(round_summary['round_no']),
        'display_round_no': int(round_summary['round_no']),
        'display_title': str(round_summary['display_title']),
        'matches': items,
    }


def merge_flatout2_missing_match_rounds(
    stage, rounds: list[dict]
) -> list[dict]:
    expected_round_summaries = get_flatout2_expected_round_summaries(stage)
    if not expected_round_summaries:
        return rounds

    rounds_by_round_no = {
        int(round_data['round_no']): round_data for round_data in rounds
    }

    return [
        rounds_by_round_no.get(
            int(round_summary['round_no']),
            build_flatout2_placeholder_match_round(stage, round_summary),
        )
        for round_summary in expected_round_summaries
    ]


def merge_flatout2_missing_bracket_rounds(
    stage, rounds: list[dict]
) -> list[dict]:
    expected_round_summaries = get_flatout2_expected_round_summaries(stage)
    if not expected_round_summaries:
        return rounds

    rounds_by_round_no = {
        int(round_data['round_no']): round_data for round_data in rounds
    }

    return [
        rounds_by_round_no.get(
            int(round_summary['round_no']),
            build_flatout2_placeholder_bracket_round(stage, round_summary),
        )
        for round_summary in expected_round_summaries
    ]

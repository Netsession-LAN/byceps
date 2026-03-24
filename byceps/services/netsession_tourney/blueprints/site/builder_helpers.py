"""
byceps.services.netsession_tourney.blueprints.site.builder_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from .ffa_single_elimination_rendering import (
    get_ffa_single_elimination_round_title,
)
from .stage_filters import _is_flatout2_stage


def _get_builder_container_child_stage_ids(stage) -> list[str]:
    settings = stage.settings or {}
    raw_stage_ids = settings.get('builder_materialized_stage_ids') or []
    if not raw_stage_ids and settings.get('builder_role') == 'preliminary':
        raw_stage_ids = settings.get('builder_materialized_group_stage_ids') or []
    return [str(stage_id) for stage_id in raw_stage_ids if stage_id]


def _is_materialized_builder_container_stage(stage) -> bool:
    settings = stage.settings or {}
    return (
        settings.get('builder_kind') == 'stage_builder_v1'
        and bool(_get_builder_container_child_stage_ids(stage))
    )


def _has_materialized_builder_container_stage(stages) -> bool:
    return any(_is_materialized_builder_container_stage(stage) for stage in stages)


def _get_materialized_builder_container_stages(
    stages,
    *,
    role: str | None = None,
):
    return [
        stage
        for stage in sorted(stages, key=lambda item: item.order_no)
        if _is_materialized_builder_container_stage(stage)
        and (role is None or (stage.settings or {}).get('builder_role') == role)
    ]


def _get_builder_container_child_stages(stages, container_stage):
    child_stage_ids = set(_get_builder_container_child_stage_ids(container_stage))
    return [
        stage
        for stage in sorted(stages, key=lambda item: item.order_no)
        if str(stage.id) in child_stage_ids
    ]


def _build_pending_builder_round_summary_lines(stage) -> list[str]:
    settings = stage.settings or {}
    source_mode = settings.get('participant_source_mode')
    if source_mode == 'stage_match_qualifiers':
        return [
            gettext(
                'Diese Runde startet, sobald die vorherige Runde abgeschlossen und die Qualifikanten übernommen wurden.'
            )
        ]
    if source_mode == 'stage_qualifiers':
        return [
            gettext(
                'Diese Runde startet, sobald die vorherige Builder-Stufe abgeschlossen ist.'
            )
        ]
    return [gettext('Diese Runde wurde noch nicht vorbereitet.')]


def _get_flatout2_builder_expected_round_summaries(stage) -> list[dict[str, int | str]]:
    if not _is_flatout2_stage(stage):
        return []

    settings = stage.settings or {}

    raw_rounds = settings.get('flatout2_rounds')
    if isinstance(raw_rounds, list):
        parsed_rounds = []
        total_round_count = len(raw_rounds)
        for index, raw_round in enumerate(raw_rounds, start=1):
            if not isinstance(raw_round, dict):
                continue

            try:
                round_no = int(raw_round.get('round_no') or index)
                match_count = int(raw_round.get('match_count') or 0)
                max_heat_size = int(settings.get('max_players_per_match') or 0)
            except (TypeError, ValueError):
                continue

            if round_no < 1 or match_count < 1 or max_heat_size < 1:
                continue

            display_title = str(
                raw_round.get('display_title')
                or raw_round.get('title')
                or ('Finale' if index == total_round_count else f'Runde {round_no}')
            ).strip()
            parsed_rounds.append(
                {
                    'round_no': round_no,
                    'match_count': match_count,
                    'max_heat_size': max_heat_size,
                    'display_title': display_title,
                }
            )

        if parsed_rounds:
            return parsed_rounds

    if settings.get('builder_materialized_round_stage'):
        try:
            round_no = int(settings.get('builder_display_round_no') or 1)
            match_count = int(settings.get('builder_expected_match_count') or 0)
            max_heat_size = int(
                settings.get('builder_expected_max_heat_size')
                or settings.get('max_players_per_match')
                or 0
            )
        except (TypeError, ValueError):
            return []

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

    raw_round_summaries = settings.get('builder_expected_round_summaries')
    if not isinstance(raw_round_summaries, list):
        return []

    parsed_round_summaries = []
    total_round_count = len(raw_round_summaries)
    for index, raw_round_summary in enumerate(raw_round_summaries, start=1):
        if not isinstance(raw_round_summary, dict):
            continue

        try:
            round_no = int(raw_round_summary.get('round_no') or index)
            match_count = int(raw_round_summary.get('match_count') or 0)
            max_heat_size = int(
                raw_round_summary.get('max_heat_size')
                or settings.get('max_players_per_match')
                or 0
            )
        except (TypeError, ValueError):
            continue

        if match_count < 1:
            continue

        parsed_round_summaries.append(
            {
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
        )

    return parsed_round_summaries


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


def _build_flatout2_placeholder_match_round(stage, round_summary: dict) -> dict:
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


def _build_flatout2_placeholder_bracket_round(stage, round_summary: dict) -> dict:
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


def _merge_flatout2_missing_match_rounds(stage, rounds: list[dict]) -> list[dict]:
    expected_round_summaries = _get_flatout2_builder_expected_round_summaries(stage)
    if not expected_round_summaries:
        return rounds

    rounds_by_round_no = {
        int(round_data['round_no']): round_data for round_data in rounds
    }

    merged_rounds = []
    for round_summary in expected_round_summaries:
        round_no = int(round_summary['round_no'])
        merged_rounds.append(
            rounds_by_round_no.get(
                round_no,
                _build_flatout2_placeholder_match_round(stage, round_summary),
            )
        )

    return merged_rounds


def _merge_flatout2_missing_bracket_rounds(stage, rounds: list[dict]) -> list[dict]:
    expected_round_summaries = _get_flatout2_builder_expected_round_summaries(stage)
    if not expected_round_summaries:
        return rounds

    rounds_by_round_no = {
        int(round_data['round_no']): round_data for round_data in rounds
    }

    merged_rounds = []
    for round_summary in expected_round_summaries:
        round_no = int(round_summary['round_no'])
        merged_rounds.append(
            rounds_by_round_no.get(
                round_no,
                _build_flatout2_placeholder_bracket_round(stage, round_summary),
            )
        )

    return merged_rounds

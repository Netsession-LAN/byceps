"""
byceps.services.netsession_tourney.blueprints.site.builder_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from .flatout2_round_helpers import (
    build_flatout2_placeholder_bracket_round,
    build_flatout2_placeholder_match_round,
    get_flatout2_expected_round_summaries as _get_flatout2_builder_expected_round_summaries,
)


def _get_raw_builder_container_child_stage_ids(settings) -> list:
    raw_stage_ids = settings.get('builder_materialized_stage_ids') or []
    if raw_stage_ids or settings.get('builder_role') != 'preliminary':
        return raw_stage_ids

    return settings.get('builder_materialized_group_stage_ids') or []


def get_builder_container_child_stage_ids(stage) -> list[str]:
    settings = stage.settings or {}
    raw_stage_ids = _get_raw_builder_container_child_stage_ids(settings)
    return [str(stage_id) for stage_id in raw_stage_ids if stage_id]


def is_materialized_builder_container_stage(stage) -> bool:
    settings = stage.settings or {}
    return settings.get('builder_kind') == 'stage_builder_v1' and bool(
        get_builder_container_child_stage_ids(stage)
    )


def has_materialized_builder_container_stage(stages) -> bool:
    return any(
        is_materialized_builder_container_stage(stage) for stage in stages
    )


def get_materialized_builder_container_stages(
    stages,
    *,
    role: str | None = None,
):
    return [
        stage
        for stage in sorted(stages, key=lambda item: item.order_no)
        if is_materialized_builder_container_stage(stage)
        and (role is None or (stage.settings or {}).get('builder_role') == role)
    ]


def get_builder_container_child_stages(stages, container_stage):
    child_stage_ids = set(
        get_builder_container_child_stage_ids(container_stage)
    )
    return [
        stage
        for stage in sorted(stages, key=lambda item: item.order_no)
        if str(stage.id) in child_stage_ids
    ]


def build_pending_builder_round_summary_lines(stage) -> list[str]:
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
                'Diese Runde startet, sobald die vorherige Stufe abgeschlossen ist.'
            )
        ]
    return [gettext('Diese Runde wurde noch nicht vorbereitet.')]


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


def _merge_flatout2_missing_match_rounds(
    stage, rounds: list[dict]
) -> list[dict]:
    expected_round_summaries = _get_flatout2_builder_expected_round_summaries(
        stage
    )
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
                build_flatout2_placeholder_match_round(stage, round_summary),
            )
        )

    return merged_rounds


def _merge_flatout2_missing_bracket_rounds(
    stage, rounds: list[dict]
) -> list[dict]:
    expected_round_summaries = _get_flatout2_builder_expected_round_summaries(
        stage
    )
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
                build_flatout2_placeholder_bracket_round(stage, round_summary),
            )
        )

    return merged_rounds

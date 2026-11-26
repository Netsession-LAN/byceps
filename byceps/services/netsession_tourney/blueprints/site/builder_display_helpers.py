"""
byceps.services.netsession_tourney.blueprints.site.builder_display_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.models import StageType

from .builder_helpers import (
    get_builder_container_child_stages,
    get_materialized_builder_container_stages,
    is_materialized_builder_container_stage,
)
from .stage_filters import _is_flatout2_stage


def _has_materialized_builder_round_robin_summary_stage(stages) -> bool:
    return any(
        _is_materialized_builder_round_robin_summary_stage(stage)
        for stage in stages
    )


def _get_materialized_builder_round_robin_summary_stage(stages):
    return next(
        (
            stage
            for stage in sorted(stages, key=lambda item: item.order_no)
            if _is_materialized_builder_round_robin_summary_stage(stage)
        ),
        None,
    )


def get_materialized_builder_round_robin_group_stages(stages):
    summary_stage = _get_materialized_builder_round_robin_summary_stage(stages)
    if summary_stage is None:
        return []

    return [
        stage
        for stage in sorted(stages, key=lambda item: item.order_no)
        if (stage.settings or {}).get('builder_role') == 'preliminary_group'
        and (stage.settings or {}).get('builder_preliminary_stage_id')
        == str(summary_stage.id)
    ]


def _get_builder_main_stages(stages):
    return [
        stage
        for stage in sorted(stages, key=lambda item: item.order_no)
        if (stage.settings or {}).get('builder_kind') == 'stage_builder_v1'
        and (stage.settings or {}).get('builder_role') == 'main'
    ]


def get_builder_main_display_stages(stages):
    display_stages = []
    for stage in _get_builder_main_stages(stages):
        if is_materialized_builder_container_stage(stage):
            display_stages.extend(
                child_stage
                for child_stage in get_builder_container_child_stages(
                    stages, stage
                )
                if _is_main_display_child_stage(child_stage)
            )
        else:
            display_stages.append(stage)

    return display_stages


def _is_main_display_child_stage(child_stage) -> bool:
    return not (child_stage.settings or {}).get('builder_role') or str(
        (child_stage.settings or {}).get('builder_role')
    ).startswith('main')


def select_matches_for_public_bracket(stages, matches):
    preliminary_containers = get_materialized_builder_container_stages(
        stages, role='preliminary'
    )
    if not preliminary_containers:
        return matches

    main_display_stages = get_builder_main_display_stages(stages)
    if not main_display_stages:
        return []

    main_stage_ids = {stage.id for stage in main_display_stages}
    return [match for match in matches if match.stage_id in main_stage_ids]


def _is_materialized_builder_round_robin_summary_stage(stage) -> bool:
    settings = stage.settings or {}
    return (
        settings.get('builder_kind') == 'stage_builder_v1'
        and settings.get('builder_role') == 'preliminary'
        and stage.type == StageType.round_robin_groups
        and bool(settings.get('builder_materialized_group_stage_ids'))
    )


def build_builder_stage_summary_lines(stage, stages) -> list[str]:
    settings = stage.settings or {}
    if settings.get('builder_materialized_stage_ids'):
        return _build_round_container_summary_lines(stage, stages)

    return _build_group_summary_lines(stage, stages, settings)


def _build_round_container_summary_lines(stage, stages) -> list[str]:
    lines = [
        gettext(
            'Diese Vorrunden-Übersicht enthält eigene Rundenphasen, die nacheinander vorbereitet und gespielt werden.'
        )
    ]
    child_stages = get_builder_container_child_stages(stages, stage)
    if child_stages:
        lines.append(
            gettext(
                '%(count)s Rundenphasen: %(names)s',
                count=len(child_stages),
                names=', '.join(stage_item.name for stage_item in child_stages),
            )
        )

    _append_main_stage_line(lines, stage, stages)
    return lines


def _build_group_summary_lines(stage, stages, settings) -> list[str]:
    lines = [
        gettext(
            'Diese Vorrunden-Übersicht fasst die Gruppenphase zusammen. Die eigentlichen Matches liegen in den Gruppenphasen.'
        )
    ]

    group_stages = _get_summary_group_stages(stages, settings)
    if group_stages:
        lines.append(
            gettext(
                '%(count)s Gruppenphasen: %(names)s',
                count=len(group_stages),
                names=', '.join(stage_item.name for stage_item in group_stages),
            )
        )

    qualifier_top_n = settings.get('builder_materialized_qualifiers_per_group')
    if qualifier_top_n:
        lines.append(
            gettext(
                'Qualifikation: Top %(top_n)s pro Gruppe ins Hauptturnier.',
                top_n=qualifier_top_n,
            )
        )

    _append_main_stage_line(lines, stage, stages)
    return lines


def _get_summary_group_stages(stages, settings) -> list:
    group_stage_ids = {
        str(stage_id)
        for stage_id in settings.get('builder_materialized_group_stage_ids', [])
    }
    return [
        stage_item
        for stage_item in stages
        if str(stage_item.id) in group_stage_ids
    ]


def _append_main_stage_line(lines: list[str], stage, stages) -> None:
    main_stage = _find_main_stage_for_preliminary(stage, stages)
    if main_stage is not None:
        lines.append(gettext('Hauptturnier: %(name)s', name=main_stage.name))


def _find_main_stage_for_preliminary(stage, stages):
    return next(
        (
            stage_item
            for stage_item in stages
            if (stage_item.settings or {}).get('builder_role') == 'main'
            and (stage_item.settings or {}).get('builder_preliminary_stage_id')
            == str(stage.id)
        ),
        None,
    )


def get_flatout2_builder_bracket_display_stages(stages):
    display_stages = []

    for container_stage in get_materialized_builder_container_stages(
        stages, role='preliminary'
    ):
        for child_stage in get_builder_container_child_stages(
            stages, container_stage
        ):
            if _is_flatout2_stage(child_stage):
                display_stages.append(child_stage)

    for stage in get_builder_main_display_stages(stages):
        if _is_flatout2_stage(stage):
            display_stages.append(stage)

    return display_stages

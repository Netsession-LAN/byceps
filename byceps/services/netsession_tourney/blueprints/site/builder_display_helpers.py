"""
byceps.services.netsession_tourney.blueprints.site.builder_display_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from .builder_display_round_robin import (
    get_materialized_builder_round_robin_group_stages as get_materialized_builder_round_robin_group_stages,
)
from .builder_display_summary_lines import (
    build_builder_stage_summary_lines as build_builder_stage_summary_lines,
)
from .builder_helpers import (
    get_builder_container_child_stages,
    get_materialized_builder_container_stages,
    is_materialized_builder_container_stage,
)
from .stage_filters import _is_flatout2_stage


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

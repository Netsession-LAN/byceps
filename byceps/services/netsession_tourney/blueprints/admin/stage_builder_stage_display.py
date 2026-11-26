"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_display
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Kinds of stage builder stages, and the stage rows and tabs
shown in the admin.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.blueprints.site.builder_helpers import (
    get_builder_container_child_stage_ids,
)
from byceps.services.netsession_tourney.models import (
    Stage,
    StageType,
)


def _is_stage_builder_v1_stage(stage: Stage) -> bool:
    return (stage.settings or {}).get('builder_kind') == 'stage_builder_v1'


def is_builder_round_robin_summary_stage(stage: Stage) -> bool:
    settings = stage.settings or {}
    return (
        _is_stage_builder_v1_stage(stage)
        and settings.get('builder_role') == 'preliminary'
        and stage.type == StageType.round_robin_groups
    )


def _is_builder_container_stage(stage: Stage) -> bool:
    return _is_stage_builder_v1_stage(stage) and bool(
        get_builder_container_child_stage_ids(stage)
    )


def _is_builder_preliminary_group_stage(stage: Stage) -> bool:
    settings = stage.settings or {}
    return (
        _is_stage_builder_v1_stage(stage)
        and settings.get('builder_role') == 'preliminary_group'
    )


def is_builder_main_stage_with_preliminary_source(stage: Stage) -> bool:
    settings = stage.settings or {}
    return (
        _is_stage_builder_v1_stage(stage)
        and settings.get('builder_role') == 'main'
        and bool(settings.get('builder_preliminary_stage_id'))
    )


def build_stage_display_rows(stages: list[Stage]) -> list[dict]:
    rows = []
    consumed_stage_ids: set = set()
    stages_by_id = {str(stage.id): stage for stage in stages}

    for stage in sorted(stages, key=lambda item: item.order_no):
        if stage.id in consumed_stage_ids:
            continue

        if _is_builder_container_stage(stage):
            row = _build_container_display_row(stage, stages_by_id)
            consumed_stage_ids.update(
                child_stage.id for child_stage in row['child_stages']
            )
            rows.append(row)
            continue

        rows.append({'kind': 'stage', 'stage': stage})

    return rows


def _build_container_display_row(
    stage: Stage, stages_by_id: dict[str, Stage]
) -> dict:
    child_stages = [
        stages_by_id[str(stage_id)]
        for stage_id in get_builder_container_child_stage_ids(stage)
        if str(stage_id) in stages_by_id
    ]
    return {
        'kind': 'builder_container',
        'stage': stage,
        'child_stages': child_stages,
    }


def build_visible_stage_tabs(stages: list[Stage]) -> list[Stage]:
    return [stage for stage in stages if not _is_builder_container_stage(stage)]

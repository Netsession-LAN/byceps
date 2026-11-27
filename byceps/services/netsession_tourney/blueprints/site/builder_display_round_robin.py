"""
byceps.services.netsession_tourney.blueprints.site.builder_display_round_robin
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Materialized round robin groups of builder stages.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.models import StageType

from .builder_display_summary_lines import (
    build_builder_stage_summary_lines as build_builder_stage_summary_lines,
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


def _is_materialized_builder_round_robin_summary_stage(stage) -> bool:
    settings = stage.settings or {}
    return (
        settings.get('builder_kind') == 'stage_builder_v1'
        and settings.get('builder_role') == 'preliminary'
        and stage.type == StageType.round_robin_groups
        and bool(settings.get('builder_materialized_group_stage_ids'))
    )

"""
byceps.services.netsession_tourney.stage_builder_resolution
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Resolving a planned stage builder stage for match generation.
"""

from __future__ import annotations

from byceps.util.result import Err, Ok, Result

from .models import (
    Stage,
    StageType,
)
from .round_robin_builder import (
    resolve_round_robin_builder_plan,
)
from .stage_builder_settings import (
    get_stage_builder_main_stage_size,
    is_stage_builder_v1_preliminary_stage,
)
from .swiss_thresholds import (
    get_swiss_threshold_for_stage,
    SWISS_THRESHOLDS,
)


def resolve_stage_builder_stage_for_generation(
    stage: Stage,
    *,
    participant_count: int,
) -> Result[Stage, str]:
    if not is_stage_builder_v1_preliminary_stage(stage):
        return Ok(stage)

    main_stage_size = get_stage_builder_main_stage_size(stage)
    if main_stage_size is None:
        return Err('Ungültige Größe des Hauptturniers im Baukasten.')

    if participant_count <= main_stage_size:
        return Err(
            'Vorrunde ist mit der aktuellen Anzahl bereiter Teilnehmer nicht nötig.'
        )

    if stage.type == StageType.round_robin_groups:
        return _resolve_round_robin_builder_stage(
            stage,
            participant_count=participant_count,
            main_stage_size=main_stage_size,
        )

    if stage.type == StageType.swiss:
        return _check_swiss_builder_stage(
            stage, participant_count=participant_count
        )

    return Ok(stage)


def _resolve_round_robin_builder_stage(
    stage: Stage,
    *,
    participant_count: int,
    main_stage_size: int,
) -> Result[Stage, str]:
    plan_result = resolve_round_robin_builder_plan(
        participant_count=participant_count,
        main_stage_size=main_stage_size,
        round_robin_builder_mode=stage.settings.get('builder_round_robin_mode'),
        round_robin_group_count=stage.settings.get(
            'builder_round_robin_group_count'
        ),
    )
    if plan_result.is_err():
        return Err(plan_result.unwrap_err())

    plan = plan_result.unwrap()
    resolved_settings = dict(stage.settings)
    resolved_settings['group_count'] = plan.group_count
    resolved_settings['builder_resolved_qualifiers_per_group'] = (
        plan.qualifiers_per_group
    )
    resolved_settings['builder_resolved_group_size_min'] = plan.min_group_size
    resolved_settings['builder_resolved_group_size_max'] = plan.max_group_size
    return Ok(
        Stage(
            id=stage.id,
            tournament_id=stage.tournament_id,
            order_no=stage.order_no,
            type=stage.type,
            name=stage.name,
            settings=resolved_settings,
            status=stage.status,
        )
    )


def _check_swiss_builder_stage(
    stage: Stage, *, participant_count: int
) -> Result[Stage, str]:
    threshold = get_swiss_threshold_for_stage(
        stage, participant_count=participant_count
    )
    if threshold not in SWISS_THRESHOLDS and participant_count > 1:
        return Err('Ungültige Swiss-Schwelle.')
    return Ok(stage)

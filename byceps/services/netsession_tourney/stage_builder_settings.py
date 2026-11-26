"""
byceps.services.netsession_tourney.stage_builder_settings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage builder (version 1): markers, sizes and the stages it generated.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .dbmodels import (
    DbNetsessionTourneyStage,
)
from .models import (
    ParticipantID,
    Stage,
    StageType,
)
from .stage_builder_settings_db import (
    delete_builder_generated_child_stages as delete_builder_generated_child_stages,
    delete_builder_generated_group_stages as delete_builder_generated_group_stages,
    detach_builder_main_stage_from_preliminary_stage as detach_builder_main_stage_from_preliminary_stage,
    find_builder_main_stage_for_preliminary_stage as find_builder_main_stage_for_preliminary_stage,
)


@dataclass(frozen=True, kw_only=True)
class RoundRobinBuilderPlan:
    group_count: int
    qualifiers_per_group: int
    min_group_size: int
    max_group_size: int
    mode: str = 'standard'


STAGE_BUILDER_KIND_V1 = 'stage_builder_v1'


STAGE_BUILDER_MAIN_STAGE_SIZES = {
    8,
    16,
    32,
    64,
    128,
    256,
    512,
    1024,
}


@dataclass(frozen=True, kw_only=True)
class BuilderGroupStageSpec:
    label: str
    participant_ids: list[ParticipantID]
    qualifiers_per_group: int


def get_divisors(number: int) -> list[int]:
    divisors: set[int] = set()
    for candidate in range(1, int(math.sqrt(number)) + 1):
        if number % candidate != 0:
            continue
        divisors.add(candidate)
        divisors.add(number // candidate)

    return sorted(divisors)


def build_group_label(index: int) -> str:
    label = ''
    value = index
    while True:
        value, remainder = divmod(value, 26)
        label = chr(ord('A') + remainder) + label
        if value == 0:
            return label
        value -= 1


def is_stage_builder_v1_main_stage(stage: Stage) -> bool:
    return (stage.settings or {}).get(
        'builder_kind'
    ) == STAGE_BUILDER_KIND_V1 and (stage.settings or {}).get(
        'builder_role'
    ) == 'main'


def is_stage_builder_v1_preliminary_stage(stage: Stage) -> bool:
    return (stage.settings or {}).get(
        'builder_kind'
    ) == STAGE_BUILDER_KIND_V1 and (stage.settings or {}).get(
        'builder_role'
    ) == 'preliminary'


def is_stage_builder_v1_main_stage_with_locked_qualifier_seeding(
    stage: Stage,
) -> bool:
    settings = stage.settings or {}
    return (
        settings.get('builder_kind') == STAGE_BUILDER_KIND_V1
        and settings.get('builder_role') == 'main'
        and bool(settings.get('builder_preliminary_stage_id'))
    )


def get_stage_builder_main_stage_size(stage: Stage) -> int | None:
    raw_value = (stage.settings or {}).get('builder_main_stage_size')
    try:
        parsed = int(raw_value)
    except TypeError, ValueError:
        return None

    return parsed if parsed in STAGE_BUILDER_MAIN_STAGE_SIZES else None


def is_builder_round_robin_summary_db_stage(
    db_stage: DbNetsessionTourneyStage,
) -> bool:
    settings = db_stage.settings_json or {}
    return (
        settings.get('builder_kind') == STAGE_BUILDER_KIND_V1
        and settings.get('builder_role') == 'preliminary'
        and db_stage.type == StageType.round_robin_groups.value
    )


def is_builder_container_db_stage(
    db_stage: DbNetsessionTourneyStage,
) -> bool:
    settings = db_stage.settings_json or {}
    has_materialized_stage_ids = bool(
        settings.get('builder_materialized_stage_ids')
    )
    has_materialized_group_stage_ids = (
        bool(settings.get('builder_materialized_group_stage_ids'))
        and settings.get('builder_role') == 'preliminary'
    )
    return settings.get('builder_kind') == STAGE_BUILDER_KIND_V1 and bool(
        has_materialized_stage_ids or has_materialized_group_stage_ids
    )

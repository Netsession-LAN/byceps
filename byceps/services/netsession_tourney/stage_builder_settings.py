"""
byceps.services.netsession_tourney.stage_builder_settings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage builder (version 1): markers, sizes and the stages it generated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

from sqlalchemy import select

from byceps.database import db
from byceps.services.user.models import User

from .dbmodels import (
    DbNetsessionTourneyStage,
)
from .models import (
    ParticipantID,
    Stage,
    StageID,
    StageType,
    TournamentID,
)
from .service_helpers import (
    _append_audit_log,
)
from .stage_activation import (
    _delete_stage_matches,
)


@dataclass(frozen=True, kw_only=True)
class _RoundRobinBuilderPlan:
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
class _BuilderGroupStageSpec:
    label: str
    participant_ids: list[ParticipantID]
    qualifiers_per_group: int


def _get_divisors(number: int) -> list[int]:
    divisors: set[int] = set()
    for candidate in range(1, int(math.sqrt(number)) + 1):
        if number % candidate != 0:
            continue
        divisors.add(candidate)
        divisors.add(number // candidate)

    return sorted(divisors)


def _build_group_label(index: int) -> str:
    label = ''
    value = index
    while True:
        value, remainder = divmod(value, 26)
        label = chr(ord('A') + remainder) + label
        if value == 0:
            return label
        value -= 1


def _find_builder_main_stage_for_preliminary_stage(
    tournament_id: TournamentID, preliminary_stage_id: StageID
) -> DbNetsessionTourneyStage | None:
    for db_stage in db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ):
        settings = db_stage.settings_json or {}
        if (
            settings.get('builder_role') == 'main'
            and settings.get('builder_preliminary_stage_id')
            == str(preliminary_stage_id)
        ):
            return db_stage

    return None


def _is_stage_builder_v1_main_stage(stage: Stage) -> bool:
    return (
        (stage.settings or {}).get('builder_kind') == STAGE_BUILDER_KIND_V1
        and (stage.settings or {}).get('builder_role') == 'main'
    )


def _is_stage_builder_v1_preliminary_stage(stage: Stage) -> bool:
    return (
        (stage.settings or {}).get('builder_kind') == STAGE_BUILDER_KIND_V1
        and (stage.settings or {}).get('builder_role') == 'preliminary'
    )


def _is_stage_builder_v1_main_stage_with_locked_qualifier_seeding(
    stage: Stage,
) -> bool:
    settings = stage.settings or {}
    return (
        settings.get('builder_kind') == STAGE_BUILDER_KIND_V1
        and settings.get('builder_role') == 'main'
        and bool(settings.get('builder_preliminary_stage_id'))
    )


def _get_stage_builder_main_stage_size(stage: Stage) -> int | None:
    raw_value = (stage.settings or {}).get('builder_main_stage_size')
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return None

    return parsed if parsed in STAGE_BUILDER_MAIN_STAGE_SIZES else None


def _is_builder_round_robin_summary_db_stage(
    db_stage: DbNetsessionTourneyStage,
) -> bool:
    settings = db_stage.settings_json or {}
    return (
        settings.get('builder_kind') == STAGE_BUILDER_KIND_V1
        and settings.get('builder_role') == 'preliminary'
        and db_stage.type == StageType.round_robin_groups.value
    )


def _is_builder_container_db_stage(
    db_stage: DbNetsessionTourneyStage,
) -> bool:
    settings = db_stage.settings_json or {}
    has_materialized_stage_ids = bool(
        settings.get('builder_materialized_stage_ids')
    )
    has_materialized_group_stage_ids = bool(
        settings.get('builder_materialized_group_stage_ids')
    ) and settings.get('builder_role') == 'preliminary'
    return settings.get('builder_kind') == STAGE_BUILDER_KIND_V1 and bool(
        has_materialized_stage_ids or has_materialized_group_stage_ids
    )


def _get_builder_generated_group_db_stages(
    tournament_id: TournamentID, preliminary_stage_id: StageID
) -> list[DbNetsessionTourneyStage]:
    db_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ).all()

    return [
        db_stage
        for db_stage in db_stages
        if (db_stage.settings_json or {}).get('builder_role')
        == 'preliminary_group'
        and (db_stage.settings_json or {}).get('builder_preliminary_stage_id')
        == str(preliminary_stage_id)
    ]


def _get_builder_generated_child_db_stages(
    tournament_id: TournamentID, parent_stage_id: StageID
) -> list[DbNetsessionTourneyStage]:
    db_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ).all()

    return [
        db_stage
        for db_stage in db_stages
        if (db_stage.settings_json or {}).get('builder_parent_stage_id')
        == str(parent_stage_id)
    ]


def _delete_builder_generated_child_stages(
    tournament_id: TournamentID,
    parent_stage_id: StageID,
    *,
    initiator: User,
) -> None:
    now = datetime.utcnow()
    for db_child_stage in _get_builder_generated_child_db_stages(
        tournament_id, parent_stage_id
    ):
        _delete_stage_matches(db_child_stage.id)
        db.session.delete(db_child_stage)
        _append_audit_log(
            actor_user_id=initiator.id,
            object_type='stage',
            object_id=db_child_stage.id,
            action='stage_deleted',
            payload={
                'name': db_child_stage.name,
                'type': db_child_stage.type,
                'deleted_by_builder_container': True,
            },
            created_at=now,
        )


def _delete_builder_generated_group_stages(
    tournament_id: TournamentID,
    preliminary_stage_id: StageID,
    *,
    initiator: User,
) -> None:
    now = datetime.utcnow()
    for db_group_stage in _get_builder_generated_group_db_stages(
        tournament_id, preliminary_stage_id
    ):
        _delete_stage_matches(db_group_stage.id)
        db.session.delete(db_group_stage)
        _append_audit_log(
            actor_user_id=initiator.id,
            object_type='stage',
            object_id=db_group_stage.id,
            action='stage_deleted',
            payload={
                'name': db_group_stage.name,
                'type': db_group_stage.type,
                'deleted_by_builder_container': True,
            },
            created_at=now,
        )


def _detach_builder_main_stage_from_preliminary_stage(
    tournament_id: TournamentID, preliminary_stage_id: StageID
) -> None:
    db_main_stage = _find_builder_main_stage_for_preliminary_stage(
        tournament_id, preliminary_stage_id
    )
    if db_main_stage is None:
        return

    settings = dict(db_main_stage.settings_json or {})
    settings.pop('builder_preliminary_stage_id', None)
    settings.pop('qualifier_source_stage_ids', None)
    settings.pop('qualifier_selection_mode', None)
    settings.pop('qualifier_top_n', None)
    settings.pop('builder_auto_qualifier_count', None)
    settings.pop('builder_materialized_group_stage_ids', None)
    settings['participant_source_mode'] = 'tournament'
    db_main_stage.settings_json = settings

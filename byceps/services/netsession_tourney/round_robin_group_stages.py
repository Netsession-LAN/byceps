"""
byceps.services.netsession_tourney.round_robin_group_stages
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage builder: a round robin preliminary is split into one real stage per
group; the main stage then takes the best of each group.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from byceps.database import db
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import DbNetsessionTourneyStage
from .models import StageID, StageStatus, StageType, TournamentID
from .service_helpers import append_audit_log
from .stage_builder_settings import BuilderGroupStageSpec


# Settings of the preliminary that every group stage takes over.
INHERITED_SETTING_KEYS = {
    'builder_kind',
    'builder_generation_basis',
    'builder_main_stage_size',
    'match_duration_minutes',
    'max_matches_per_round',
    'break_between_rounds_minutes',
    'result_report_mode',
}


def read_group_plan(
    stage_settings: dict[str, Any],
) -> Result[tuple[int, int], str]:
    """Return group count and qualifiers per group."""
    try:
        group_count = int(stage_settings.get('group_count'))
        qualifiers_per_group = int(
            stage_settings.get('builder_resolved_qualifiers_per_group')
        )
    except (TypeError, ValueError):
        return Err('Builder-Gruppenplan ist ungültig.')

    if group_count < 1 or qualifiers_per_group < 1:
        return Err('Builder-Gruppenplan ist unvollständig.')

    return Ok((group_count, qualifiers_per_group))


def shift_following_stages(
    tournament_id: TournamentID, db_stage: DbNetsessionTourneyStage, by: int
) -> None:
    """Make room for the group stages right after the preliminary."""
    db_stages_to_shift = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .filter(DbNetsessionTourneyStage.order_no > db_stage.order_no)
        .order_by(DbNetsessionTourneyStage.order_no.desc())
    ).all()
    for db_other_stage in db_stages_to_shift:
        db_other_stage.order_no += by


def create_group_stage(
    tournament_id: TournamentID,
    db_stage: DbNetsessionTourneyStage,
    index: int,
    group_stage_spec: BuilderGroupStageSpec,
    *,
    preliminary_settings: dict[str, Any],
    initiator: User,
    now: datetime,
) -> DbNetsessionTourneyStage:
    group_settings = {
        key: value
        for key, value in preliminary_settings.items()
        if key in INHERITED_SETTING_KEYS
    }
    group_settings.update(
        {
            'group_count': 1,
            'participant_source_mode': 'builder_fixed_participants',
            'builder_role': 'preliminary_group',
            'builder_preliminary_stage_id': str(db_stage.id),
            'builder_group_label': group_stage_spec.label,
            'builder_group_qualifier_top_n': group_stage_spec.qualifiers_per_group,
            'builder_fixed_participant_ids': [
                str(participant_id)
                for participant_id in group_stage_spec.participant_ids
            ],
        }
    )
    db_group_stage = DbNetsessionTourneyStage(
        StageID(generate_uuid7()),
        tournament_id,
        db_stage.order_no + index,
        StageType.round_robin_groups,
        f'Vorrunde Gruppe {group_stage_spec.label}',
        now,
        settings_json=group_settings,
    )
    db.session.add(db_group_stage)

    append_audit_log(
        actor_user_id=initiator.id,
        object_type='stage',
        object_id=db_group_stage.id,
        action='stage_created',
        payload={
            'type': StageType.round_robin_groups.value,
            'name': db_group_stage.name,
            'settings': group_settings,
            'created_by_builder_materialization': True,
        },
        created_at=now,
    )
    return db_group_stage


def mark_preliminary_split(
    db_stage: DbNetsessionTourneyStage,
    settings: dict[str, Any],
    group_stage_ids: list[StageID],
    qualifiers_per_group: int,
    now: datetime,
) -> None:
    """The preliminary becomes a closed overview of its group stages."""
    settings['builder_materialized_group_stage_ids'] = [
        str(stage_id) for stage_id in group_stage_ids
    ]
    settings['builder_materialized_group_count'] = len(group_stage_ids)
    settings['builder_materialized_qualifiers_per_group'] = qualifiers_per_group
    settings['builder_materialized_at'] = now.isoformat()
    db_stage.settings_json = settings
    db_stage.status = StageStatus.closed.value
    db_stage.name = 'Vorrunden-Übersicht'


def point_main_stage_at_groups(
    db_main_stage: DbNetsessionTourneyStage,
    group_stage_ids: list[StageID],
    qualifiers_per_group: int,
) -> None:
    main_settings = dict(db_main_stage.settings_json or {})
    main_settings['participant_source_mode'] = 'stage_qualifiers'
    main_settings['qualifier_source_stage_ids'] = [
        str(stage_id) for stage_id in group_stage_ids
    ]
    main_settings['qualifier_selection_mode'] = 'per_stage'
    main_settings['qualifier_top_n'] = qualifiers_per_group
    main_settings['builder_auto_qualifier_count'] = False
    main_settings['builder_materialized_group_stage_ids'] = [
        str(stage_id) for stage_id in group_stage_ids
    ]
    db_main_stage.settings_json = main_settings

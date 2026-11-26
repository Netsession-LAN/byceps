"""
byceps.services.netsession_tourney.stage_builder_settings_db
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Database lookups and clean-up for stage builder stages: the main stage
of a preliminary and the generated child and group stages.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from byceps.database import db
from byceps.services.user.models import User

from .dbmodels import (
    DbNetsessionTourneyStage,
)
from .models import (
    StageID,
    TournamentID,
)
from .service_helpers import (
    append_audit_log,
)
from .stage_activation import (
    delete_stage_matches,
)


def find_builder_main_stage_for_preliminary_stage(
    tournament_id: TournamentID, preliminary_stage_id: StageID
) -> DbNetsessionTourneyStage | None:
    for db_stage in db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ):
        settings = db_stage.settings_json or {}
        if settings.get('builder_role') == 'main' and settings.get(
            'builder_preliminary_stage_id'
        ) == str(preliminary_stage_id):
            return db_stage

    return None


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


def delete_builder_generated_child_stages(
    tournament_id: TournamentID,
    parent_stage_id: StageID,
    *,
    initiator: User,
) -> None:
    now = datetime.utcnow()
    for db_child_stage in _get_builder_generated_child_db_stages(
        tournament_id, parent_stage_id
    ):
        delete_stage_matches(db_child_stage.id)
        db.session.delete(db_child_stage)
        append_audit_log(
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


def delete_builder_generated_group_stages(
    tournament_id: TournamentID,
    preliminary_stage_id: StageID,
    *,
    initiator: User,
) -> None:
    now = datetime.utcnow()
    for db_group_stage in _get_builder_generated_group_db_stages(
        tournament_id, preliminary_stage_id
    ):
        delete_stage_matches(db_group_stage.id)
        db.session.delete(db_group_stage)
        append_audit_log(
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


def detach_builder_main_stage_from_preliminary_stage(
    tournament_id: TournamentID, preliminary_stage_id: StageID
) -> None:
    db_main_stage = find_builder_main_stage_for_preliminary_stage(
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

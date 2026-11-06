"""
byceps.services.netsession_tourney.builder_auto_generation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage builder: main stages are generated as soon as their preliminaries are complete.
"""

from __future__ import annotations

from sqlalchemy import select
import structlog

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User, UserID

from .dbmodels import (
    DbNetsessionTourneyStage,
)
from .match_generation import (
    _generate_stage_matches,
)
from .models import (
    StageID,
    TournamentID,
)
from .stage_builder_settings import (
    STAGE_BUILDER_KIND_V1,
)
from .stage_service import (
    _is_stage_fully_completed,
    _parse_source_stage_ids,
    _stage_has_assigned_participants,
    _stage_has_reported_results,
)


log = structlog.get_logger()


def _auto_generate_builder_main_stages_from_completed_source(
    *,
    party_id: PartyID,
    tournament_id: TournamentID,
    source_stage_id: StageID,
    actor_user_id: UserID,
    correlation_id: str | None,
) -> None:
    if not _is_stage_fully_completed(tournament_id, source_stage_id):
        return

    db_candidate_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ).all()

    for db_stage in db_candidate_stages:
        settings = dict(db_stage.settings_json or {})
        if (
            settings.get('builder_kind') != STAGE_BUILDER_KIND_V1
            or settings.get('builder_role') != 'main'
            or settings.get('participant_source_mode') != 'stage_qualifiers'
        ):
            continue

        source_stage_ids = _parse_source_stage_ids(
            settings.get('qualifier_source_stage_ids', [])
        )
        if source_stage_id not in source_stage_ids:
            continue
        if not source_stage_ids:
            continue
        if not all(
            _is_stage_fully_completed(tournament_id, stage_id)
            for stage_id in source_stage_ids
        ):
            continue
        if _stage_has_assigned_participants(tournament_id, db_stage.id):
            continue
        if _stage_has_reported_results(tournament_id, db_stage.id):
            continue

        initiator = User(
            id=actor_user_id,
            screen_name=None,
            initialized=True,
            suspended=False,
            deleted=False,
            avatar_url='',
        )
        savepoint = db.session.begin_nested()
        result = _generate_stage_matches(
            party_id,
            tournament_id,
            db_stage.id,
            initiator,
            correlation_id=correlation_id,
        )
        if result.is_err():
            savepoint.rollback()
            log.warning(
                'netsession_tourney.builder_main_auto_generation_failed',
                tournament_id=str(tournament_id),
                source_stage_id=str(source_stage_id),
                target_stage_id=str(db_stage.id),
                reason=result.unwrap_err(),
                correlation_id=correlation_id,
            )
            continue
        savepoint.commit()

        log.info(
            'netsession_tourney.builder_main_auto_generated',
            tournament_id=str(tournament_id),
            source_stage_id=str(source_stage_id),
            target_stage_id=str(db_stage.id),
            match_count=len(result.unwrap()),
            correlation_id=correlation_id,
        )

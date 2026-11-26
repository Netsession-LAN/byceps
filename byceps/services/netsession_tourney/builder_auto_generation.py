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
    is_stage_fully_completed,
    parse_source_stage_ids,
    stage_has_assigned_participants,
    stage_has_reported_results,
)


log = structlog.get_logger()


def auto_generate_builder_main_stages_from_completed_source(
    *,
    party_id: PartyID,
    tournament_id: TournamentID,
    source_stage_id: StageID,
    actor_user_id: UserID,
    correlation_id: str | None,
) -> None:
    if not is_stage_fully_completed(tournament_id, source_stage_id):
        return

    db_candidate_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ).all()

    for db_stage in db_candidate_stages:
        if not _is_builder_main_stage_ready_for_auto_generation(
            db_stage, tournament_id, source_stage_id
        ):
            continue

        _auto_generate_builder_main_stage(
            party_id=party_id,
            tournament_id=tournament_id,
            source_stage_id=source_stage_id,
            db_stage=db_stage,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )


def _is_builder_main_stage_ready_for_auto_generation(
    db_stage: DbNetsessionTourneyStage,
    tournament_id: TournamentID,
    source_stage_id: StageID,
) -> bool:
    source_stage_ids = _get_builder_main_stage_source_stage_ids(db_stage)
    if source_stage_ids is None:
        return False

    if source_stage_id not in source_stage_ids:
        return False
    if not source_stage_ids:
        return False
    if not all(
        is_stage_fully_completed(tournament_id, stage_id)
        for stage_id in source_stage_ids
    ):
        return False

    return _is_stage_untouched(tournament_id, db_stage.id)


def _get_builder_main_stage_source_stage_ids(
    db_stage: DbNetsessionTourneyStage,
) -> list[StageID] | None:
    """Return the qualifier source stages of a builder main stage, or
    `None` if the stage is not a builder main stage fed by qualifiers."""
    settings = dict(db_stage.settings_json or {})
    if (
        settings.get('builder_kind') != STAGE_BUILDER_KIND_V1
        or settings.get('builder_role') != 'main'
        or settings.get('participant_source_mode') != 'stage_qualifiers'
    ):
        return None

    return parse_source_stage_ids(
        settings.get('qualifier_source_stage_ids', [])
    )


def _is_stage_untouched(tournament_id: TournamentID, stage_id: StageID) -> bool:
    if stage_has_assigned_participants(tournament_id, stage_id):
        return False
    if stage_has_reported_results(tournament_id, stage_id):
        return False
    return True


def _auto_generate_builder_main_stage(
    *,
    party_id: PartyID,
    tournament_id: TournamentID,
    source_stage_id: StageID,
    db_stage: DbNetsessionTourneyStage,
    actor_user_id: UserID,
    correlation_id: str | None,
) -> None:
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
        return
    savepoint.commit()

    log.info(
        'netsession_tourney.builder_main_auto_generated',
        tournament_id=str(tournament_id),
        source_stage_id=str(source_stage_id),
        target_stage_id=str(db_stage.id),
        match_count=len(result.unwrap()),
        correlation_id=correlation_id,
    )

"""
byceps.services.netsession_tourney.match_generation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Generating the matches of a stage (and the group stages of a round robin preliminary).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from sqlalchemy import select
import structlog

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyStage,
)
from .discord_service import (
    enqueue_discord_event,
)
from .match_advancement import (
    _auto_advance_byes,
)
from .match_schedule import (
    _persist_generated_matches,
    _schedule_generated_matches,
)
from .models import (
    Match,
    MatchState,
    StageID,
    StageStatus,
    StageType,
    TournamentID,
    TournamentStatus,
)
from .notification_service import (
    _enqueue_match_ready_notifications,
)
from .round_robin_builder import (
    _build_round_robin_builder_group_stage_specs,
)
from .round_robin_group_stages import (
    create_group_stage,
    mark_preliminary_split,
    point_main_stage_at_groups,
    read_group_plan,
    shift_following_stages,
)
from .service_helpers import (
    _append_audit_log,
)
from .stage_activation import (
    _delete_stage_matches,
)
from .stage_builder_settings import (
    _find_builder_main_stage_for_preliminary_stage,
    _is_stage_builder_v1_preliminary_stage,
)
from .stage_generation import (
    _build_stage_generation_payload,
)
from .stage_generation_base import (
    _StageGenerationPayload,
)


log = structlog.get_logger()


def generate_stage_matches(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
    initiator: User,
    *,
    correlation_id: str | None = None,
    round_starts_at_by_round_no: dict[int, datetime] | None = None,
    stage_settings_patch: dict[str, Any] | None = None,
    match_settings_by_round_and_match_no: (
        dict[tuple[int, int], dict[str, Any]] | None
    ) = None,
) -> Result[list[Match], str]:
    payload_result = _build_stage_generation_payload(
        party_id,
        tournament_id,
        stage_id,
        stage_settings_override=stage_settings_patch,
    )
    if payload_result.is_err():
        return Err(payload_result.unwrap_err())
    payload = payload_result.unwrap()

    db_stage = db.session.scalar(
        select(DbNetsessionTourneyStage).filter_by(
            id=stage_id, tournament_id=tournament_id
        )
    )
    if db_stage is None:
        return Err('Unbekannte Stage.')

    if (
        _is_stage_builder_v1_preliminary_stage(payload.stage)
        and payload.stage.type == StageType.round_robin_groups
    ):
        return _materialize_round_robin_builder_group_stages(
            party_id=party_id,
            tournament_id=tournament_id,
            db_stage=db_stage,
            payload=payload,
            initiator=initiator,
            correlation_id=correlation_id,
            round_starts_at_by_round_no=round_starts_at_by_round_no,
        )

    if stage_settings_patch:
        merged_stage_settings = dict(db_stage.settings_json or {})
        merged_stage_settings.update(stage_settings_patch)
        db_stage.settings_json = merged_stage_settings
        payload = replace(
            payload,
            stage=replace(payload.stage, settings=merged_stage_settings),
        )

    if payload.replace_existing_matches:
        _delete_stage_matches(stage_id)
    matches = _persist_generated_matches(
        tournament_id=tournament_id,
        stage_id=stage_id,
        specs=payload.match_specs,
        match_settings_by_round_and_match_no=match_settings_by_round_and_match_no,
    )
    _schedule_generated_matches(
        tournament_starts_at=payload.tournament.starts_at,
        stage=payload.stage,
        match_ids=[match.id for match in matches],
        round_starts_at_by_round_no=round_starts_at_by_round_no,
    )

    stage_started_now = False
    if (
        payload.tournament.status == TournamentStatus.live
        and db_stage.status == StageStatus.draft.value
    ):
        db_stage.status = StageStatus.live.value
        stage_started_now = True

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='stage',
        object_id=stage_id,
        action='matches_generated',
        payload={
            'match_count': len(matches),
            'correlation_id': correlation_id,
        },
        created_at=datetime.utcnow(),
    )
    db.session.commit()

    if stage_started_now:
        enqueue_discord_event(
            party_id,
            tournament_id,
            event_name='stage_started',
            payload={
                'stage_id': str(stage_id),
                'stage_name': payload.stage.name,
            },
        )

    if payload.tournament.status == TournamentStatus.live:
        for match in matches:
            if match.state != MatchState.ready:
                continue
            db_match = db.session.get(DbNetsessionTourneyMatch, match.id)
            if db_match is None or db_match.state != MatchState.ready.value:
                continue
            _enqueue_match_ready_notifications(db_match)
        db.session.commit()

    _auto_advance_byes(
        tournament_id, payload.stage, engine=payload.engine
    )

    log.info(
        'netsession_tourney.matches_generated',
        tournament_id=str(tournament_id),
        stage_id=str(stage_id),
        actor_user_id=str(initiator.id),
        correlation_id=correlation_id,
        match_count=len(matches),
    )

    return Ok(matches)


def _materialize_round_robin_builder_group_stages(
    *,
    party_id: PartyID,
    tournament_id: TournamentID,
    db_stage: DbNetsessionTourneyStage,
    payload: _StageGenerationPayload,
    initiator: User,
    correlation_id: str | None,
    round_starts_at_by_round_no: dict[int, datetime] | None,
) -> Result[list[Match], str]:
    settings = dict(db_stage.settings_json or {})
    if settings.get('builder_materialized_group_stage_ids'):
        return Err(
            'Diese Builder-Vorrunde wurde bereits in echte Gruppen-Stages aufgeteilt.'
        )

    group_plan_result = read_group_plan(payload.stage.settings)
    if group_plan_result.is_err():
        return Err(group_plan_result.unwrap_err())
    group_count, qualifiers_per_group = group_plan_result.unwrap()

    group_stage_specs = _build_round_robin_builder_group_stage_specs(
        payload.participants,
        group_count=group_count,
        qualifiers_per_group=qualifiers_per_group,
    )
    if not group_stage_specs:
        return Err('Es konnten keine Builder-Gruppen erzeugt werden.')

    db_main_stage = _find_builder_main_stage_for_preliminary_stage(
        tournament_id, db_stage.id
    )
    if db_main_stage is None:
        return Err('Das Builder-Hauptturnier zur Vorrunde konnte nicht gefunden werden.')

    shift_following_stages(tournament_id, db_stage, len(group_stage_specs))

    now = datetime.utcnow()
    group_stage_ids = [
        create_group_stage(
            tournament_id,
            db_stage,
            index,
            group_stage_spec,
            preliminary_settings=settings,
            initiator=initiator,
            now=now,
        ).id
        for index, group_stage_spec in enumerate(group_stage_specs, start=1)
    ]
    mark_preliminary_split(
        db_stage, settings, group_stage_ids, qualifiers_per_group, now
    )
    point_main_stage_at_groups(db_main_stage, group_stage_ids, qualifiers_per_group)

    db.session.commit()

    created_matches: list[Match] = []
    for group_stage_id in group_stage_ids:
        generated_matches_result = generate_stage_matches(
            party_id,
            tournament_id,
            group_stage_id,
            initiator,
            correlation_id=correlation_id,
            round_starts_at_by_round_no=round_starts_at_by_round_no,
        )
        if generated_matches_result.is_err():
            return Err(generated_matches_result.unwrap_err())
        created_matches.extend(generated_matches_result.unwrap())

    return Ok(created_matches)

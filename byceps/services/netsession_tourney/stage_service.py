"""
byceps.services.netsession_tourney.stage_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stages of a tournament: create, update, delete, and their settings.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyStage,
)
from .engines.registry import (
    get_stage_type_spec,
    get_stage_type_specs,
)
from .models import (
    MatchState,
    RegistrationMode,
    Stage,
    StageFamily,
    StageID,
    StageType,
    TournamentID,
    TournamentMode,
    TournamentStatus,
)
from .registration_validation import (
    _is_stage_type_compatible_with_registration_mode,
)
from .service_helpers import (
    _append_audit_log,
    _db_stage_to_model,
)
from .stage_activation import (
    _delete_stage_matches,
)
from .stage_builder_settings import (
    _delete_builder_generated_child_stages,
    _delete_builder_generated_group_stages,
    _detach_builder_main_stage_from_preliminary_stage,
    _is_builder_container_db_stage,
    _is_builder_round_robin_summary_db_stage,
)
from .tournament_queries import (
    _find_db_tournament_for_party,
)


def get_available_stage_type_specs():
    return get_stage_type_specs()


def _parse_source_stage_ids(raw_source_stage_ids: Any) -> list[StageID]:
    if not isinstance(raw_source_stage_ids, list):
        return []

    source_stage_ids: list[StageID] = []
    for raw_stage_id in raw_source_stage_ids:
        try:
            source_stage_ids.append(StageID(UUID(str(raw_stage_id))))
        except ValueError:
            continue

    return source_stage_ids


def create_stage(
    party_id: PartyID,
    tournament_id: TournamentID,
    type_: StageType,
    name: str,
    settings: dict[str, Any],
    initiator: User,
) -> Result[Stage, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    spec = get_stage_type_spec(type_)
    tournament_mode = TournamentMode(db_tournament.mode)
    if not _is_stage_type_compatible_with_tournament_mode(
        spec.family, tournament_mode
    ):
        return Err('Dieser Stage-Typ passt nicht zum Turniermodus.')

    tournament_registration_mode = RegistrationMode(db_tournament.registration_mode)
    if not _is_stage_type_compatible_with_registration_mode(
        type_, tournament_registration_mode
    ):
        return Err('Dieser Stage-Typ passt nicht zum Anmeldemodus.')

    if not spec.enabled:
        return Err('Dieser Stage-Typ ist zurzeit deaktiviert.')

    max_order_no = db.session.scalar(
        select(db.func.max(DbNetsessionTourneyStage.order_no)).filter_by(
            tournament_id=tournament_id
        )
    )
    order_no = (max_order_no or 0) + 1

    db_stage = DbNetsessionTourneyStage(
        StageID(generate_uuid7()),
        tournament_id,
        order_no,
        type_,
        name.strip(),
        datetime.utcnow(),
        settings_json=dict(settings),
    )
    db.session.add(db_stage)

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='stage',
        object_id=db_stage.id,
        action='stage_created',
        payload={'type': type_.value, 'name': name, 'settings': settings},
        created_at=datetime.utcnow(),
    )

    db.session.commit()
    return Ok(_db_stage_to_model(db_stage))


def update_stage(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
    type_: StageType,
    name: str,
    settings: dict[str, Any],
    initiator: User,
) -> Result[Stage, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    if db_tournament.status != TournamentStatus.draft.value:
        return Err('Stages lassen sich nur im Entwurf ändern.')

    db_stage = db.session.scalar(
        select(DbNetsessionTourneyStage).filter_by(
            id=stage_id, tournament_id=tournament_id
        )
    )
    if db_stage is None:
        return Err('Unbekannte Stage.')

    spec = get_stage_type_spec(type_)
    tournament_mode = TournamentMode(db_tournament.mode)
    if not _is_stage_type_compatible_with_tournament_mode(
        spec.family, tournament_mode
    ):
        return Err('Dieser Stage-Typ passt nicht zum Turniermodus.')

    tournament_registration_mode = RegistrationMode(db_tournament.registration_mode)
    if not _is_stage_type_compatible_with_registration_mode(
        type_, tournament_registration_mode
    ):
        return Err('Dieser Stage-Typ passt nicht zum Anmeldemodus.')

    if not spec.enabled:
        return Err('Dieser Stage-Typ ist zurzeit deaktiviert.')

    # Matches need regeneration after structural stage changes.
    _delete_stage_matches(stage_id)

    db_stage.type = type_.value
    db_stage.name = name.strip()
    db_stage.settings_json = dict(settings)

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='stage',
        object_id=stage_id,
        action='stage_updated',
        payload={
            'type': type_.value,
            'name': name,
            'settings': settings,
        },
        created_at=datetime.utcnow(),
    )

    db.session.commit()
    return Ok(_db_stage_to_model(db_stage))


def delete_stage(
    party_id: PartyID,
    tournament_id: TournamentID,
    stage_id: StageID,
    initiator: User,
) -> Result[None, str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    if db_tournament.status != TournamentStatus.draft.value:
        return Err('Stages lassen sich nur im Entwurf ändern.')

    db_stage = db.session.scalar(
        select(DbNetsessionTourneyStage).filter_by(
            id=stage_id, tournament_id=tournament_id
        )
    )
    if db_stage is None:
        return Err('Unbekannte Stage.')

    if _is_builder_round_robin_summary_db_stage(db_stage):
        _delete_builder_generated_group_stages(
            tournament_id,
            db_stage.id,
            initiator=initiator,
        )
        _detach_builder_main_stage_from_preliminary_stage(
            tournament_id, db_stage.id
        )
    elif _is_builder_container_db_stage(db_stage):
        _delete_builder_generated_child_stages(
            tournament_id,
            db_stage.id,
            initiator=initiator,
        )

    _delete_stage_matches(stage_id)
    db.session.delete(db_stage)
    # Flush the deletion first so the subsequent renumbering does not
    # temporarily collide with the still-persisted (tournament_id, order_no)
    # unique constraint.
    db.session.flush()
    _renumber_stages_for_tournament(tournament_id)

    _append_audit_log(
        actor_user_id=initiator.id,
        object_type='stage',
        object_id=stage_id,
        action='stage_deleted',
        payload={'name': db_stage.name, 'type': db_stage.type},
        created_at=datetime.utcnow(),
    )

    db.session.commit()
    return Ok(None)


def _is_stage_fully_completed(
    tournament_id: TournamentID, stage_id: StageID
) -> bool:
    total_match_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatch.id)).filter_by(
            tournament_id=tournament_id,
            stage_id=stage_id,
        )
    )
    if not total_match_count:
        return False

    incomplete_match_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatch.id))
        .filter_by(
            tournament_id=tournament_id,
            stage_id=stage_id,
        )
        .filter(DbNetsessionTourneyMatch.state != MatchState.completed.value)
    )
    return int(incomplete_match_count or 0) == 0


def _stage_has_assigned_participants(
    tournament_id: TournamentID, stage_id: StageID
) -> bool:
    assigned_participant_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatchSlot.id))
        .join(
            DbNetsessionTourneyMatch,
            DbNetsessionTourneyMatch.id == DbNetsessionTourneyMatchSlot.match_id,
        )
        .filter(
            DbNetsessionTourneyMatch.tournament_id == tournament_id,
            DbNetsessionTourneyMatch.stage_id == stage_id,
            DbNetsessionTourneyMatchSlot.participant_id.is_not(None),
        )
    )
    return bool(assigned_participant_count)


def _stage_has_reported_results(
    tournament_id: TournamentID, stage_id: StageID
) -> bool:
    result_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyMatchResult.id))
        .join(
            DbNetsessionTourneyMatch,
            DbNetsessionTourneyMatch.id == DbNetsessionTourneyMatchResult.match_id,
        )
        .filter(
            DbNetsessionTourneyMatch.tournament_id == tournament_id,
            DbNetsessionTourneyMatch.stage_id == stage_id,
        )
    )
    return bool(result_count)


def _renumber_stages_for_tournament(tournament_id: TournamentID) -> None:
    db_stages = db.session.scalars(
        select(DbNetsessionTourneyStage)
        .filter_by(tournament_id=tournament_id)
        .order_by(DbNetsessionTourneyStage.order_no.asc())
    ).all()

    if not db_stages:
        return

    max_order_no = max(db_stage.order_no for db_stage in db_stages)
    temporary_order_no_base = max_order_no + len(db_stages) + 1

    # Move all rows out of the currently occupied order_no range first so the
    # final compacting step cannot violate the per-tournament unique
    # constraint, even if the UPDATE statements are executed in bulk.
    for index, db_stage in enumerate(db_stages, start=0):
        db_stage.order_no = temporary_order_no_base + index

    db.session.flush()

    for index, db_stage in enumerate(db_stages, start=1):
        db_stage.order_no = index


def _is_stage_type_compatible_with_tournament_mode(
    stage_family: StageFamily,
    tournament_mode: TournamentMode,
) -> bool:
    if tournament_mode == TournamentMode.duel:
        return stage_family == StageFamily.duel

    if tournament_mode == TournamentMode.ffa:
        return stage_family == StageFamily.ffa

    return False


def _get_stage_setting_int(
    settings: dict[str, Any],
    key: str,
    *,
    minimum: int,
    fallback: int | None = None,
) -> int | None:
    raw_value = settings.get(key, fallback)
    if raw_value is None:
        return None

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return fallback

    if value < minimum:
        return fallback

    return value

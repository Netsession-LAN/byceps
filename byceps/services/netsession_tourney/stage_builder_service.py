"""
byceps.services.netsession_tourney.stage_builder_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage builder: creating the stages of a planned tournament format.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from .dbmodels import (
    DbNetsessionTourneyStage,
)
from .ffa_stage_builder_plan import (
    _build_ffa_stage_builder_plan,
)
from .match_schedule import (
    _build_pending_structure_match_specs_for_stage,
    _persist_generated_matches,
)
from .models import (
    Stage,
    StageID,
    StageType,
    TournamentID,
    TournamentMode,
    TournamentStatus,
)
from .result_report_mode import (
    RESULT_REPORT_MODE_ADMIN_ONLY,
)
from .service_helpers import (
    _append_audit_log,
    _db_stage_to_model,
)
from .stage_builder_settings import (
    STAGE_BUILDER_KIND_V1,
    STAGE_BUILDER_MAIN_STAGE_SIZES,
)
from .swiss_thresholds import (
    _get_swiss_round_count_for_threshold,
    SWISS_THRESHOLDS,
)
from .tournament_queries import (
    _find_db_tournament_for_party,
)


def build_stage_builder_plan(
    party_id: PartyID,
    tournament_id: TournamentID,
    *,
    generation_basis: str,
    main_stage_type: StageType,
    main_stage_size: int,
    max_players_per_match: int | None,
    preliminary_type: StageType | None,
    round_robin_builder_mode: str | None,
    round_robin_group_count: int | None,
    swiss_threshold: int | None,
    match_duration_minutes: int | None,
    max_matches_per_round: int | None,
    break_between_rounds_minutes: int | None,
    initiator: User,
) -> Result[list[Stage], str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    if db_tournament.status != TournamentStatus.draft.value:
        return Err(
            'Die Stage-Struktur kann nur im Draft-Status aufgebaut werden.'
        )

    existing_stage_count = db.session.scalar(
        select(db.func.count(DbNetsessionTourneyStage.id)).filter_by(
            tournament_id=tournament_id
        )
    )
    if existing_stage_count:
        return Err(
            'Für den Stage Builder V1 muss das Turnier noch keine Stages haben.'
        )

    tournament_mode = TournamentMode(db_tournament.mode)
    if tournament_mode == TournamentMode.ffa:
        return _build_ffa_stage_builder_plan(
            party_id,
            tournament_id,
            generation_basis=generation_basis,
            main_stage_type=main_stage_type,
            main_stage_size=main_stage_size,
            max_players_per_match=max_players_per_match,
            preliminary_type=preliminary_type,
            match_duration_minutes=match_duration_minutes,
            max_matches_per_round=max_matches_per_round,
            break_between_rounds_minutes=break_between_rounds_minutes,
            initiator=initiator,
        )

    if tournament_mode != TournamentMode.duel:
        return Err('Der Stage Builder V1 unterstützt diesen Turniermodus nicht.')

    if main_stage_type not in {
        StageType.single_elimination,
        StageType.double_elimination,
        StageType.double_elimination_double_grand_final,
    }:
        return Err('Dieser Main-Stage-Typ wird vom Baukasten nicht unterstützt.')

    if main_stage_size not in STAGE_BUILDER_MAIN_STAGE_SIZES:
        return Err('Ungültige Größe der Main Stage.')

    if generation_basis != 'ready':
        return Err('Ungültige Grundlage für die Erzeugung.')

    if preliminary_type not in {
        None,
        StageType.round_robin_groups,
        StageType.swiss,
    }:
        return Err('Dieser Vorrunden-Typ wird vom Baukasten nicht unterstützt.')

    if preliminary_type == StageType.round_robin_groups:
        if round_robin_builder_mode not in {None, 'standard', 'manual_group_count'}:
            return Err('Ungültige Round-Robin-Strategie.')
        if round_robin_builder_mode == 'manual_group_count':
            if round_robin_group_count is None or round_robin_group_count < 2:
                return Err(
                    'Für die Expertenoption muss eine gültige Gruppenzahl gewählt werden.'
                )

    if preliminary_type == StageType.swiss:
        if swiss_threshold not in SWISS_THRESHOLDS:
            return Err('Swiss preliminaries require a valid threshold.')

    if match_duration_minutes is not None and (
        match_duration_minutes < 1 or match_duration_minutes > 240
    ):
        return Err('Ungültige Matchdauer.')

    if max_matches_per_round is not None and (
        max_matches_per_round < 1 or max_matches_per_round > 256
    ):
        return Err('Ungültige Höchstzahl an Matches pro Runde.')

    if break_between_rounds_minutes is not None and (
        break_between_rounds_minutes < 0
        or break_between_rounds_minutes > 240
    ):
        return Err('Ungültige Pause zwischen den Runden.')

    now = datetime.utcnow()
    created_stages: list[DbNetsessionTourneyStage] = []

    preliminary_stage: DbNetsessionTourneyStage | None = None
    if preliminary_type is not None:
        preliminary_settings = {
            'participant_source_mode': 'tournament',
            'builder_kind': STAGE_BUILDER_KIND_V1,
            'builder_role': 'preliminary',
            'builder_generation_basis': generation_basis,
            'builder_main_stage_size': main_stage_size,
            'builder_auto_skip_if_not_needed': True,
            'result_report_mode': RESULT_REPORT_MODE_ADMIN_ONLY
            if preliminary_type == StageType.swiss
            else 'both_must_confirm',
        }
        if preliminary_type == StageType.swiss:
            preliminary_settings['swiss_threshold'] = swiss_threshold
            preliminary_settings['round_count'] = (
                _get_swiss_round_count_for_threshold(swiss_threshold)
            )
        elif preliminary_type == StageType.round_robin_groups:
            preliminary_settings['builder_round_robin_mode'] = (
                round_robin_builder_mode or 'standard'
            )
            if round_robin_group_count is not None:
                preliminary_settings['builder_round_robin_group_count'] = (
                    round_robin_group_count
                )
        if match_duration_minutes is not None:
            preliminary_settings['match_duration_minutes'] = (
                match_duration_minutes
            )
        if max_matches_per_round is not None:
            preliminary_settings['max_matches_per_round'] = (
                max_matches_per_round
            )
        if break_between_rounds_minutes is not None:
            preliminary_settings['break_between_rounds_minutes'] = (
                break_between_rounds_minutes
            )

        preliminary_stage = DbNetsessionTourneyStage(
            StageID(generate_uuid7()),
            tournament_id,
            1,
            preliminary_type,
            'Vorrunde',
            now,
            settings_json=preliminary_settings,
        )
        db.session.add(preliminary_stage)
        created_stages.append(preliminary_stage)

    main_stage_order_no = 2 if preliminary_stage is not None else 1
    main_stage_settings: dict[str, Any] = {
        'builder_kind': STAGE_BUILDER_KIND_V1,
        'builder_role': 'main',
        'builder_generation_basis': generation_basis,
        'builder_main_stage_size': main_stage_size,
        'result_report_mode': 'both_must_confirm',
    }
    if preliminary_stage is None:
        main_stage_settings['participant_source_mode'] = 'tournament'
    else:
        main_stage_settings['participant_source_mode'] = 'stage_qualifiers'
        main_stage_settings['qualifier_source_stage_ids'] = [
            str(preliminary_stage.id)
        ]
        main_stage_settings['qualifier_selection_mode'] = (
            'per_group'
            if preliminary_type == StageType.round_robin_groups
            else 'per_stage'
        )
        main_stage_settings['qualifier_top_n'] = (
            main_stage_size if preliminary_type == StageType.swiss else 1
        )
        main_stage_settings['builder_auto_qualifier_count'] = True
        main_stage_settings['builder_preliminary_stage_id'] = str(
            preliminary_stage.id
        )
    if match_duration_minutes is not None:
        main_stage_settings['match_duration_minutes'] = match_duration_minutes
    if max_matches_per_round is not None:
        main_stage_settings['max_matches_per_round'] = max_matches_per_round
    if break_between_rounds_minutes is not None:
        main_stage_settings['break_between_rounds_minutes'] = (
            break_between_rounds_minutes
        )

    main_stage = DbNetsessionTourneyStage(
        StageID(generate_uuid7()),
        tournament_id,
        main_stage_order_no,
        main_stage_type,
        'Hauptturnier',
        now,
        settings_json=main_stage_settings,
    )
    db.session.add(main_stage)
    created_stages.append(main_stage)

    if preliminary_stage is not None:
        # Ensure the newly created stage row exists before inserting
        # structure-only matches that reference its `stage_id`.
        db.session.flush()

        pending_specs_result = _build_pending_structure_match_specs_for_stage(
            tournament_id=tournament_id,
            stage_type=main_stage_type,
            participant_count=main_stage_size,
        )
        if pending_specs_result.is_err():
            return Err(pending_specs_result.unwrap_err())

        _persist_generated_matches(
            tournament_id=tournament_id,
            stage_id=main_stage.id,
            specs=pending_specs_result.unwrap(),
        )

    for created_stage in created_stages:
        _append_audit_log(
            actor_user_id=initiator.id,
            object_type='stage',
            object_id=created_stage.id,
            action='stage_created',
            payload={
                'type': created_stage.type,
                'name': created_stage.name,
                'settings': dict(created_stage.settings_json or {}),
                'created_by_builder': True,
            },
            created_at=now,
        )

    db.session.commit()

    return Ok([_db_stage_to_model(stage) for stage in created_stages])

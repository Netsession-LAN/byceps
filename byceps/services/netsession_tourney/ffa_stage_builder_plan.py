"""
byceps.services.netsession_tourney.ffa_stage_builder_plan
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage builder for FFA tournaments: creating the planned stages.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from byceps.database import db
from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from . import domain_service
from .dbmodels import (
    DbNetsessionTourneyStage,
)
from .ffa_stage_builder import (
    _build_ffa_stage_builder_common_settings,
    _preview_ffa_stage_builder_stage,
    _validate_ffa_stage_builder_settings,
)
from .flatout2_builder import (
    _create_flatout2_builder_round_stages,
)
from .models import (
    Stage,
    StageID,
    StageType,
    TournamentID,
)
from .service_helpers import (
    _append_audit_log,
    _db_stage_to_model,
)
from .tournament_queries import (
    get_participants_for_tournament,
)


def _build_ffa_stage_builder_plan(
    party_id: PartyID,
    tournament_id: TournamentID,
    *,
    generation_basis: str,
    main_stage_type: StageType,
    main_stage_size: int,
    max_players_per_match: int | None,
    preliminary_type: StageType | None,
    match_duration_minutes: int | None,
    max_matches_per_round: int | None,
    break_between_rounds_minutes: int | None,
    initiator: User,
) -> Result[list[Stage], str]:
    validation_result = _validate_ffa_stage_builder_settings(
        main_stage_type=main_stage_type,
        main_stage_size=main_stage_size,
        max_players_per_match=max_players_per_match,
        preliminary_type=preliminary_type,
        generation_basis=generation_basis,
    )
    if validation_result.is_err():
        return Err(validation_result.unwrap_err())

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

    if max_players_per_match is None:
        return Err('Für den FFA-Baukasten bitte die maximale Spielerzahl pro Match angeben.')

    participants = get_participants_for_tournament(party_id, tournament_id)
    ready_participants = domain_service.select_ready_participants(participants)
    participant_count = len(ready_participants)
    uses_preliminary = (
        preliminary_type is not None and participant_count > main_stage_size
    )

    now = datetime.utcnow()
    created_stages: list[DbNetsessionTourneyStage] = []
    next_order_no = 1
    preliminary_stage: DbNetsessionTourneyStage | None = None
    last_preliminary_source_stage_id: StageID | None = None

    preliminary_preview: dict[str, Any] | None = None
    if uses_preliminary and preliminary_type is not None:
        preliminary_preview_result = _preview_ffa_stage_builder_stage(
            tournament_id=tournament_id,
            stage_type=preliminary_type,
            participant_count=participant_count,
            max_players_per_match=max_players_per_match,
            stop_when_participants_at_most=(
                main_stage_size
                if preliminary_type == StageType.ffa_flatout2_single_elimination
                else None
            ),
        )
        if preliminary_preview_result.is_err():
            return Err(preliminary_preview_result.unwrap_err())
        preliminary_preview = preliminary_preview_result.unwrap()

    if uses_preliminary and preliminary_type is not None:
        preliminary_settings = _build_ffa_stage_builder_common_settings(
            generation_basis=generation_basis,
            main_stage_size=main_stage_size,
            max_players_per_match=max_players_per_match,
            match_duration_minutes=match_duration_minutes,
            max_matches_per_round=max_matches_per_round,
            break_between_rounds_minutes=break_between_rounds_minutes,
        )
        preliminary_settings.update(
            {
                'builder_role': 'preliminary',
                'participant_source_mode': 'tournament',
            }
        )

        if preliminary_type == StageType.ffa_flatout2_single_elimination:
            preliminary_stage, preliminary_round_stages = (
                _create_flatout2_builder_round_stages(
                    tournament_id=tournament_id,
                    order_no_start=next_order_no,
                    container_name='Vorrunden',
                    role='preliminary',
                    stage_type=preliminary_type,
                    round_summaries=(
                        preliminary_preview['round_summaries']
                        if preliminary_preview is not None
                        else []
                    ),
                    common_settings=preliminary_settings,
                    initial_source_mode='tournament',
                    initial_source_stage_ids=None,
                    initial_qualifier_top_n=None,
                    initial_qualifier_top_n_per_match=None,
                    now=now,
                )
            )
            created_stages.append(preliminary_stage)
            created_stages.extend(preliminary_round_stages)
            next_order_no += 1 + len(preliminary_round_stages)
            last_preliminary_source_stage_id = (
                preliminary_round_stages[-1].id if preliminary_round_stages else None
            )
        else:
            preliminary_stage = DbNetsessionTourneyStage(
                StageID(generate_uuid7()),
                tournament_id,
                next_order_no,
                preliminary_type,
                'Vorrunde',
                now,
                settings_json=preliminary_settings,
            )
            db.session.add(preliminary_stage)
            created_stages.append(preliminary_stage)
            last_preliminary_source_stage_id = preliminary_stage.id
            next_order_no += 1

    main_stage_participant_count = (
        main_stage_size if uses_preliminary else participant_count
    )
    main_preview_result = _preview_ffa_stage_builder_stage(
        tournament_id=tournament_id,
        stage_type=main_stage_type,
        participant_count=main_stage_participant_count,
        max_players_per_match=max_players_per_match,
        stop_when_participants_at_most=None,
    )
    if main_preview_result.is_err():
        return Err(main_preview_result.unwrap_err())
    main_preview = main_preview_result.unwrap()

    main_stage_settings = _build_ffa_stage_builder_common_settings(
        generation_basis=generation_basis,
        main_stage_size=main_stage_size,
        max_players_per_match=max_players_per_match,
        match_duration_minutes=match_duration_minutes,
        max_matches_per_round=max_matches_per_round,
        break_between_rounds_minutes=break_between_rounds_minutes,
    )
    main_stage_settings['builder_role'] = 'main'
    if main_stage_type == StageType.ffa_flatout2_single_elimination:
        main_stage_settings['builder_expected_round_summaries'] = (
            main_preview['round_summaries']
        )
        main_stage_settings['round_count'] = len(main_preview['round_summaries'])
    if preliminary_stage is None:
        main_stage_settings['participant_source_mode'] = 'tournament'
    else:
        if preliminary_type == StageType.ffa_flatout2_single_elimination:
            main_stage_settings['participant_source_mode'] = 'stage_match_qualifiers'
            main_stage_settings['qualifier_source_stage_ids'] = [
                str(last_preliminary_source_stage_id)
            ]
            main_stage_settings['qualifier_top_n_per_match'] = 3
        else:
            main_stage_settings['participant_source_mode'] = 'stage_qualifiers'
            main_stage_settings['qualifier_source_stage_ids'] = [
                str(preliminary_stage.id)
            ]
            main_stage_settings['qualifier_selection_mode'] = 'per_stage'
            main_stage_settings['qualifier_top_n'] = main_stage_size
            main_stage_settings['builder_auto_qualifier_count'] = False
        main_stage_settings['builder_preliminary_stage_id'] = str(
            preliminary_stage.id
        )

    main_stage_name = (
        'Finale'
        if main_stage_type == StageType.ffa_flatout2_single_elimination
        else 'Hauptturnier'
    )
    main_stage = DbNetsessionTourneyStage(
        StageID(generate_uuid7()),
        tournament_id,
        next_order_no,
        main_stage_type,
        main_stage_name,
        now,
        settings_json=main_stage_settings,
    )
    db.session.add(main_stage)
    created_stages.append(main_stage)

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

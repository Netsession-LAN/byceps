"""
byceps.services.netsession_tourney.ffa_stage_builder_plan
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage builder for FFA tournaments: creating the planned stages.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
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
    build_ffa_stage_builder_common_settings,
    preview_ffa_stage_builder_stage,
    validate_ffa_stage_builder_settings,
)
from .flatout2_builder import (
    create_flatout2_builder_round_stages,
)
from .models import (
    Stage,
    StageID,
    StageType,
    TournamentID,
)
from .service_helpers import (
    db_stage_to_model,
)
from .stage_builder_parts import audit_created_stages, StageTiming
from .tournament_queries import (
    get_participants_for_tournament,
)


def build_ffa_stage_builder_plan(
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
    input_error = _validate_ffa_builder_input(
        main_stage_type=main_stage_type,
        main_stage_size=main_stage_size,
        max_players_per_match=max_players_per_match,
        preliminary_type=preliminary_type,
        generation_basis=generation_basis,
        timing=StageTiming(
            match_duration_minutes=match_duration_minutes,
            max_matches_per_round=max_matches_per_round,
            break_between_rounds_minutes=break_between_rounds_minutes,
        ),
    )
    if input_error is not None:
        return Err(input_error)

    participant_count = _count_ready_participants(party_id, tournament_id)
    uses_preliminary = (
        preliminary_type is not None and participant_count > main_stage_size
    )

    def common_settings() -> dict[str, Any]:
        return build_ffa_stage_builder_common_settings(
            generation_basis=generation_basis,
            main_stage_size=main_stage_size,
            max_players_per_match=max_players_per_match,
            match_duration_minutes=match_duration_minutes,
            max_matches_per_round=max_matches_per_round,
            break_between_rounds_minutes=break_between_rounds_minutes,
        )

    now = datetime.utcnow()
    plan = _FfaPreliminary()
    if uses_preliminary and preliminary_type is not None:
        preliminary_result = _create_ffa_preliminary(
            tournament_id,
            preliminary_type,
            participant_count=participant_count,
            main_stage_size=main_stage_size,
            max_players_per_match=max_players_per_match,
            settings=common_settings(),
            now=now,
        )
        if preliminary_result.is_err():
            return Err(preliminary_result.unwrap_err())
        plan = preliminary_result.unwrap()

    main_stage_result = _create_ffa_main_stage(
        tournament_id,
        main_stage_type,
        main_stage_size=main_stage_size,
        participant_count=main_stage_size if uses_preliminary else participant_count,
        max_players_per_match=max_players_per_match,
        plan=plan,
        preliminary_type=preliminary_type,
        common_settings=common_settings,
        now=now,
    )
    if main_stage_result.is_err():
        return Err(main_stage_result.unwrap_err())
    created_stages = plan.created_stages + [main_stage_result.unwrap()]

    audit_created_stages(created_stages, initiator, now)
    db.session.commit()

    return Ok([db_stage_to_model(stage) for stage in created_stages])


def _count_ready_participants(
    party_id: PartyID, tournament_id: TournamentID
) -> int:
    participants = get_participants_for_tournament(party_id, tournament_id)
    return len(domain_service.select_ready_participants(participants))


@dataclass(kw_only=True)
class _FfaPreliminary:
    """The preliminary stages created so far (none by default)."""

    stage: DbNetsessionTourneyStage | None = None
    created_stages: list[DbNetsessionTourneyStage] = field(default_factory=list)
    last_source_stage_id: StageID | None = None
    next_order_no: int = 1


def _create_ffa_preliminary(
    tournament_id: TournamentID,
    preliminary_type: StageType,
    *,
    participant_count: int,
    main_stage_size: int,
    max_players_per_match: int,
    settings: dict[str, Any],
    now: datetime,
) -> Result[_FfaPreliminary, str]:
    preview_result = preview_ffa_stage_builder_stage(
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
    if preview_result.is_err():
        return Err(preview_result.unwrap_err())

    settings.update(
        {'builder_role': 'preliminary', 'participant_source_mode': 'tournament'}
    )

    if preliminary_type == StageType.ffa_flatout2_single_elimination:
        container, round_stages = create_flatout2_builder_round_stages(
            tournament_id=tournament_id,
            order_no_start=1,
            container_name='Vorrunden',
            role='preliminary',
            stage_type=preliminary_type,
            round_summaries=preview_result.unwrap()['round_summaries'],
            common_settings=settings,
            initial_source_mode='tournament',
            initial_source_stage_ids=None,
            initial_qualifier_top_n=None,
            initial_qualifier_top_n_per_match=None,
            now=now,
        )
        return Ok(
            _FfaPreliminary(
                stage=container,
                created_stages=[container, *round_stages],
                last_source_stage_id=round_stages[-1].id if round_stages else None,
                next_order_no=2 + len(round_stages),
            )
        )

    stage = DbNetsessionTourneyStage(
        StageID(generate_uuid7()),
        tournament_id,
        1,
        preliminary_type,
        'Vorrunde',
        now,
        settings_json=settings,
    )
    db.session.add(stage)
    return Ok(
        _FfaPreliminary(
            stage=stage,
            created_stages=[stage],
            last_source_stage_id=stage.id,
            next_order_no=2,
        )
    )


def _create_ffa_main_stage(
    tournament_id: TournamentID,
    main_stage_type: StageType,
    *,
    main_stage_size: int,
    participant_count: int,
    max_players_per_match: int,
    plan: _FfaPreliminary,
    preliminary_type: StageType | None,
    common_settings: Callable[[], dict[str, Any]],
    now: datetime,
) -> Result[DbNetsessionTourneyStage, str]:
    main_preview_result = preview_ffa_stage_builder_stage(
        tournament_id=tournament_id,
        stage_type=main_stage_type,
        participant_count=participant_count,
        max_players_per_match=max_players_per_match,
        stop_when_participants_at_most=None,
    )
    if main_preview_result.is_err():
        return Err(main_preview_result.unwrap_err())

    main_stage = DbNetsessionTourneyStage(
        StageID(generate_uuid7()),
        tournament_id,
        plan.next_order_no,
        main_stage_type,
        'Finale'
        if main_stage_type == StageType.ffa_flatout2_single_elimination
        else 'Hauptturnier',
        now,
        settings_json=_ffa_main_stage_settings(
            common_settings(),
            main_stage_type,
            main_stage_size,
            main_preview_result.unwrap(),
            plan,
            preliminary_type,
        ),
    )
    db.session.add(main_stage)
    return Ok(main_stage)


def _ffa_main_stage_settings(
    settings: dict[str, Any],
    main_stage_type: StageType,
    main_stage_size: int,
    main_preview: dict[str, Any],
    preliminary: _FfaPreliminary,
    preliminary_type: StageType | None,
) -> dict[str, Any]:
    settings['builder_role'] = 'main'
    if main_stage_type == StageType.ffa_flatout2_single_elimination:
        settings['builder_expected_round_summaries'] = main_preview['round_summaries']
        settings['round_count'] = len(main_preview['round_summaries'])

    if preliminary.stage is None:
        settings['participant_source_mode'] = 'tournament'
        return settings

    if preliminary_type == StageType.ffa_flatout2_single_elimination:
        settings['participant_source_mode'] = 'stage_match_qualifiers'
        settings['qualifier_source_stage_ids'] = [str(preliminary.last_source_stage_id)]
        settings['qualifier_top_n_per_match'] = 3
    else:
        settings['participant_source_mode'] = 'stage_qualifiers'
        settings['qualifier_source_stage_ids'] = [str(preliminary.stage.id)]
        settings['qualifier_selection_mode'] = 'per_stage'
        settings['qualifier_top_n'] = main_stage_size
        settings['builder_auto_qualifier_count'] = False
    settings['builder_preliminary_stage_id'] = str(preliminary.stage.id)
    return settings


def _validate_ffa_builder_input(*, timing: StageTiming, **settings) -> str | None:
    """Return an error message, or `None` if the input is fine."""
    validation_result = validate_ffa_stage_builder_settings(**settings)
    if validation_result.is_err():
        return validation_result.unwrap_err()

    timing_error = timing.validate()
    if timing_error is not None:
        return timing_error

    if settings['max_players_per_match'] is None:
        return 'Für den FFA-Baukasten bitte die maximale Spielerzahl pro Match angeben.'

    return None

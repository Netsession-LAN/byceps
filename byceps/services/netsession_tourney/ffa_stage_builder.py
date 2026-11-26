"""
byceps.services.netsession_tourney.ffa_stage_builder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage builder for FFA tournaments: settings and preview.
"""

from __future__ import annotations

from typing import Any

from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result

from . import domain_service
from .ffa_stage_builder_stage_preview import (
    preview_ffa_stage_builder_stage as preview_ffa_stage_builder_stage,
)
from .ffa_stage_builder_validation import (
    validate_ffa_stage_builder_settings as validate_ffa_stage_builder_settings,
)
from .models import (
    StageType,
    TournamentID,
    TournamentMode,
)
from .result_report_mode import (
    RESULT_REPORT_MODE_ADMIN_ONLY,
)
from .stage_builder_settings import (
    STAGE_BUILDER_KIND_V1,
)
from .tournament_queries import (
    get_participants_for_tournament,
)


def preview_ffa_stage_builder_plan(
    party_id: PartyID,
    tournament_id: TournamentID,
    *,
    generation_basis: str,
    main_stage_type: StageType,
    main_stage_size: int,
    max_players_per_match: int | None,
    preliminary_type: StageType | None,
) -> Result[dict[str, Any], str]:
    validation_result = validate_ffa_stage_builder_settings(
        main_stage_type=main_stage_type,
        main_stage_size=main_stage_size,
        max_players_per_match=max_players_per_match,
        preliminary_type=preliminary_type,
        generation_basis=generation_basis,
    )
    if validation_result.is_err():
        return Err(validation_result.unwrap_err())

    if max_players_per_match is None:
        return Err(
            'Für den FFA-Baukasten bitte die maximale Spielerzahl pro Match angeben.'
        )

    participants = get_participants_for_tournament(party_id, tournament_id)
    ready_participants = domain_service.select_ready_participants(participants)
    participant_count = len(ready_participants)

    (
        uses_preliminary,
        generation_blocked_without_preliminary,
        main_stage_participant_count,
    ) = _get_ffa_stage_builder_participant_split(
        preliminary_type, participant_count, main_stage_size
    )

    preliminary_preview_result = _preview_optional_ffa_preliminary(
        uses_preliminary=uses_preliminary,
        tournament_id=tournament_id,
        preliminary_type=preliminary_type,
        participant_count=participant_count,
        main_stage_size=main_stage_size,
        max_players_per_match=max_players_per_match,
    )
    if preliminary_preview_result.is_err():
        return Err(preliminary_preview_result.unwrap_err())
    preliminary_preview = preliminary_preview_result.unwrap()

    main_preview_result = preview_ffa_stage_builder_stage(
        tournament_id=tournament_id,
        stage_type=main_stage_type,
        participant_count=main_stage_participant_count,
        max_players_per_match=max_players_per_match,
        stop_when_participants_at_most=None,
    )
    if main_preview_result.is_err():
        return Err(main_preview_result.unwrap_err())
    main_preview = main_preview_result.unwrap()

    return Ok(
        _assemble_ffa_stage_builder_preview(
            generation_basis=generation_basis,
            main_stage_type=main_stage_type,
            main_stage_size=main_stage_size,
            participant_count=participant_count,
            preliminary_type=preliminary_type,
            uses_preliminary=uses_preliminary,
            generation_blocked_without_preliminary=(
                generation_blocked_without_preliminary
            ),
            max_players_per_match=max_players_per_match,
            main_stage_participant_count=main_stage_participant_count,
            main_preview=main_preview,
            preliminary_preview=preliminary_preview,
        )
    )


def _get_ffa_stage_builder_participant_split(
    preliminary_type: StageType | None,
    participant_count: int,
    main_stage_size: int,
) -> tuple[bool, bool, int]:
    uses_preliminary = (
        preliminary_type is not None and participant_count > main_stage_size
    )
    generation_blocked_without_preliminary = (
        preliminary_type is None and participant_count > main_stage_size
    )
    main_stage_participant_count = (
        main_stage_size
        if (uses_preliminary or generation_blocked_without_preliminary)
        else participant_count
    )
    return (
        uses_preliminary,
        generation_blocked_without_preliminary,
        main_stage_participant_count,
    )


def _preview_optional_ffa_preliminary(
    *,
    uses_preliminary: bool,
    tournament_id: TournamentID,
    preliminary_type: StageType | None,
    participant_count: int,
    main_stage_size: int,
    max_players_per_match: int,
) -> Result[dict[str, Any] | None, str]:
    if not uses_preliminary:
        return Ok(None)

    preliminary_preview_result = _preview_ffa_stage_builder_preliminary(
        tournament_id=tournament_id,
        preliminary_type=preliminary_type,
        participant_count=participant_count,
        main_stage_size=main_stage_size,
        max_players_per_match=max_players_per_match,
    )
    if preliminary_preview_result.is_err():
        return Err(preliminary_preview_result.unwrap_err())
    return Ok(preliminary_preview_result.unwrap())


def _preview_ffa_stage_builder_preliminary(
    *,
    tournament_id: TournamentID,
    preliminary_type: StageType,
    participant_count: int,
    main_stage_size: int,
    max_players_per_match: int,
) -> Result[dict[str, Any], str]:
    return preview_ffa_stage_builder_stage(
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


def _assemble_ffa_stage_builder_preview(
    *,
    generation_basis: str,
    main_stage_type: StageType,
    main_stage_size: int,
    participant_count: int,
    preliminary_type: StageType | None,
    uses_preliminary: bool,
    generation_blocked_without_preliminary: bool,
    max_players_per_match: int,
    main_stage_participant_count: int,
    main_preview: dict[str, Any],
    preliminary_preview: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        'generation_basis': generation_basis,
        'main_stage_type': main_stage_type,
        'participant_count': participant_count,
        'preliminary_type': preliminary_type,
        'needs_preliminary': participant_count > main_stage_size,
        'uses_preliminary': uses_preliminary,
        'generation_blocked_without_preliminary': (
            generation_blocked_without_preliminary
        ),
        'max_players_per_match': max_players_per_match,
        'qualifier_rule': (
            'top_3'
            if main_stage_type == StageType.ffa_flatout2_single_elimination
            else 'dynamic'
        ),
        'round_summaries': main_preview['round_summaries'],
        'match_count': main_preview['match_count'],
        'main_round_summaries': main_preview['round_summaries'],
        'main_match_count': main_preview['match_count'],
        'main_stage_participant_count': main_stage_participant_count,
        'expected_final_heat_size': main_preview['expected_final_heat_size'],
        'preliminary_round_summaries': (
            preliminary_preview['round_summaries']
            if preliminary_preview is not None
            else []
        ),
        'preliminary_match_count': (
            preliminary_preview['match_count']
            if preliminary_preview is not None
            else None
        ),
    }


def build_ffa_stage_builder_common_settings(
    *,
    generation_basis: str,
    main_stage_size: int,
    max_players_per_match: int,
    match_duration_minutes: int | None,
    max_matches_per_round: int | None,
    break_between_rounds_minutes: int | None,
) -> dict[str, Any]:
    settings: dict[str, Any] = {
        'builder_kind': STAGE_BUILDER_KIND_V1,
        'builder_generation_basis': generation_basis,
        'builder_mode': TournamentMode.ffa.value,
        'builder_main_stage_size': main_stage_size,
        'max_players_per_match': max_players_per_match,
        'result_report_mode': RESULT_REPORT_MODE_ADMIN_ONLY,
    }
    if match_duration_minutes is not None:
        settings['match_duration_minutes'] = match_duration_minutes
    if max_matches_per_round is not None:
        settings['max_matches_per_round'] = max_matches_per_round
    if break_between_rounds_minutes is not None:
        settings['break_between_rounds_minutes'] = break_between_rounds_minutes

    return settings

"""
byceps.services.netsession_tourney.ffa_stage_builder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage builder for FFA tournaments: settings and preview.
"""

from __future__ import annotations

from typing import Any

from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7

from . import domain_service
from .engines.base import MatchSpec
from .engines.registry import (
    find_stage_engine,
)
from .flatout2_builder import (
    _summarize_flatout2_builder_rounds,
)
from .models import (
    ParticipantID,
    Stage,
    StageID,
    StageStatus,
    StageType,
    TournamentID,
    TournamentMode,
)
from .result_report_mode import (
    RESULT_REPORT_MODE_ADMIN_ONLY,
)
from .stage_builder_settings import (
    STAGE_BUILDER_KIND_V1,
    STAGE_BUILDER_MAIN_STAGE_SIZES,
)
from .tournament_queries import (
    get_participants_for_tournament,
)


def _preview_ffa_stage_builder_plan(
    party_id: PartyID,
    tournament_id: TournamentID,
    *,
    generation_basis: str,
    main_stage_type: StageType,
    main_stage_size: int,
    max_players_per_match: int | None,
    preliminary_type: StageType | None,
) -> Result[dict[str, Any], str]:
    validation_result = _validate_ffa_stage_builder_settings(
        main_stage_type=main_stage_type,
        main_stage_size=main_stage_size,
        max_players_per_match=max_players_per_match,
        preliminary_type=preliminary_type,
        generation_basis=generation_basis,
    )
    if validation_result.is_err():
        return Err(validation_result.unwrap_err())

    if max_players_per_match is None:
        return Err('Für den FFA-Baukasten bitte die maximale Spielerzahl pro Match angeben.')

    participants = get_participants_for_tournament(party_id, tournament_id)
    ready_participants = domain_service.select_ready_participants(participants)
    participant_count = len(ready_participants)

    uses_preliminary = (
        preliminary_type is not None and participant_count > main_stage_size
    )
    generation_blocked_without_preliminary = (
        preliminary_type is None and participant_count > main_stage_size
    )
    preliminary_preview: dict[str, Any] | None = None
    if uses_preliminary:
        preliminary_preview_result = _preview_ffa_stage_builder_preliminary(
            tournament_id=tournament_id,
            preliminary_type=preliminary_type,
            participant_count=participant_count,
            main_stage_size=main_stage_size,
            max_players_per_match=max_players_per_match,
        )
        if preliminary_preview_result.is_err():
            return Err(preliminary_preview_result.unwrap_err())
        preliminary_preview = preliminary_preview_result.unwrap()

    main_stage_participant_count = (
        main_stage_size
        if (uses_preliminary or generation_blocked_without_preliminary)
        else participant_count
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


def _preview_ffa_stage_builder_preliminary(
    *,
    tournament_id: TournamentID,
    preliminary_type: StageType,
    participant_count: int,
    main_stage_size: int,
    max_players_per_match: int,
) -> Result[dict[str, Any], str]:
    return _preview_ffa_stage_builder_stage(
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
            if main_stage_type
            == StageType.ffa_flatout2_single_elimination
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


def _validate_ffa_stage_builder_settings(
    *,
    main_stage_type: StageType,
    main_stage_size: int,
    max_players_per_match: int | None,
    preliminary_type: StageType | None,
    generation_basis: str,
) -> Result[None, str]:
    allowed_ffa_stage_types = {
        StageType.ffa_single_elimination,
        StageType.ffa_flatout2_single_elimination,
    }
    if main_stage_type not in allowed_ffa_stage_types:
        return Err('Dieser Main-Stage-Typ wird vom FFA-Baukasten nicht unterstützt.')

    if main_stage_size not in STAGE_BUILDER_MAIN_STAGE_SIZES:
        return Err('Ungültige Größe der Main Stage.')

    if generation_basis != 'ready':
        return Err('Ungültige Grundlage für die Erzeugung.')

    if preliminary_type is not None and preliminary_type not in allowed_ffa_stage_types:
        return Err('Dieser Vorrunden-Typ wird vom FFA-Baukasten nicht unterstützt.')

    if max_players_per_match is None:
        return Err('Für den FFA-Baukasten bitte die maximale Spielerzahl pro Match angeben.')

    if max_players_per_match < 2 or max_players_per_match > 64:
        return Err('Ungültige maximale Spielerzahl pro Match.')

    if main_stage_type == StageType.ffa_flatout2_single_elimination and (
        max_players_per_match < 6 or max_players_per_match > 8
    ):
        return Err('FlatOut 2 braucht 6 bis 8 Spieler pro Match.')

    if preliminary_type == StageType.ffa_flatout2_single_elimination and (
        max_players_per_match < 6 or max_players_per_match > 8
    ):
        return Err('FlatOut 2 braucht 6 bis 8 Spieler pro Match.')

    return Ok(None)


def _build_ffa_stage_builder_common_settings(
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
        settings['break_between_rounds_minutes'] = (
            break_between_rounds_minutes
        )

    return settings


def _preview_ffa_stage_builder_stage(
    *,
    tournament_id: TournamentID,
    stage_type: StageType,
    participant_count: int,
    max_players_per_match: int,
    stop_when_participants_at_most: int | None = None,
) -> Result[dict[str, Any], str]:
    if stage_type == StageType.ffa_flatout2_single_elimination:
        round_summaries = _summarize_flatout2_builder_rounds(
            participant_count=participant_count,
            max_players_per_match=max_players_per_match,
            stop_when_participants_at_most=stop_when_participants_at_most,
        )
        return Ok(
            {
                'round_summaries': round_summaries,
                'match_count': sum(
                    round_summary['match_count']
                    for round_summary in round_summaries
                ),
                'expected_final_heat_size': (
                    round_summaries[-1]['max_heat_size']
                    if round_summaries
                    else 0
                ),
            }
        )

    engine = find_stage_engine(stage_type)
    if engine is None:
        return Err('Für diesen FFA-Stage-Typ gibt es keine Match-Erzeugung.')

    preview_stage = Stage(
        id=StageID(generate_uuid7()),
        tournament_id=tournament_id,
        order_no=1,
        type=stage_type,
        name='Preview',
        settings={'max_players_per_match': max_players_per_match},
        status=StageStatus.draft,
    )
    preview_participant_ids = [
        ParticipantID(generate_uuid7()) for _ in range(participant_count)
    ]
    generated_specs_result = engine.generate(
        preview_stage, preview_participant_ids
    )
    if generated_specs_result.is_err():
        return Err(generated_specs_result.unwrap_err())

    specs = generated_specs_result.unwrap()
    round_summaries = _summarize_ffa_builder_match_specs(specs)

    return Ok(
        {
            'round_summaries': round_summaries,
            'match_count': len(specs),
            'expected_final_heat_size': (
                round_summaries[-1]['max_heat_size'] if round_summaries else 0
            ),
        }
    )


def _summarize_ffa_builder_match_specs(
    specs: list[MatchSpec],
) -> list[dict[str, int]]:
    round_summaries = []
    for round_no in sorted({spec.round_no for spec in specs}):
        round_specs = [spec for spec in specs if spec.round_no == round_no]
        heat_sizes = [
            len(
                [
                    slot
                    for slot in spec.slots
                    if slot.participant_id is not None
                    or slot.source_match_no is not None
                ]
            )
            for spec in round_specs
        ]
        round_summaries.append(
            {
                'round_no': round_no,
                'match_count': len(round_specs),
                'max_heat_size': max(heat_sizes) if heat_sizes else 0,
            }
        )

    return round_summaries

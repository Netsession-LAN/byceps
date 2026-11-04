"""
byceps.services.netsession_tourney.stage_builder_preview
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage builder: preview of a plan and the stage to generate next.
"""

from __future__ import annotations

from typing import Any

from byceps.services.party.models import PartyID
from byceps.util.result import Err, Ok, Result

from . import domain_service
from .ffa_stage_builder import (
    _preview_ffa_stage_builder_plan,
)
from .models import (
    Stage,
    StageType,
    TournamentID,
    TournamentMode,
)
from .round_robin_builder import (
    _resolve_round_robin_builder_plan,
)
from .stage_builder_settings import (
    _get_stage_builder_main_stage_size,
    _is_stage_builder_v1_preliminary_stage,
    STAGE_BUILDER_MAIN_STAGE_SIZES,
)
from .stage_generation_base import (
    _distribute_evenly,
)
from .swiss_thresholds import (
    _get_swiss_round_count_for_threshold,
    _get_swiss_threshold_for_stage,
    SWISS_THRESHOLDS,
)
from .tournament_queries import (
    _find_db_tournament_for_party,
    get_participants_for_tournament,
)


def preview_stage_builder_plan(
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
) -> Result[dict[str, Any], str]:
    db_tournament = _find_db_tournament_for_party(party_id, tournament_id)
    if db_tournament is None:
        return Err('Unbekanntes Turnier.')

    tournament_mode = TournamentMode(db_tournament.mode)
    if tournament_mode == TournamentMode.ffa:
        return _preview_ffa_stage_builder_plan(
            party_id,
            tournament_id,
            generation_basis=generation_basis,
            main_stage_type=main_stage_type,
            main_stage_size=main_stage_size,
            max_players_per_match=max_players_per_match,
            preliminary_type=preliminary_type,
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

    participants = get_participants_for_tournament(party_id, tournament_id)
    ready_participants = domain_service.select_ready_participants(participants)
    participant_count = len(ready_participants)

    preview: dict[str, Any] = {
        'generation_basis': generation_basis,
        'main_stage_type': main_stage_type,
        'main_stage_size': main_stage_size,
        'participant_count': participant_count,
        'preliminary_type': preliminary_type,
        'needs_preliminary': (
            preliminary_type is not None and participant_count > main_stage_size
        ),
    }

    if preliminary_type is None or participant_count <= main_stage_size:
        return Ok(preview)

    if preliminary_type == StageType.round_robin_groups:
        plan_result = _resolve_round_robin_builder_plan(
            participant_count=participant_count,
            main_stage_size=main_stage_size,
            round_robin_builder_mode=round_robin_builder_mode,
            round_robin_group_count=round_robin_group_count,
        )
        if plan_result.is_err():
            return Err(plan_result.unwrap_err())

        plan = plan_result.unwrap()
        group_sizes = _distribute_evenly(participant_count, plan.group_count)
        preview.update(
            {
                'group_count': plan.group_count,
                'qualifiers_per_group': plan.qualifiers_per_group,
                'min_group_size': plan.min_group_size,
                'max_group_size': plan.max_group_size,
                'group_sizes': group_sizes,
                'round_robin_builder_mode': plan.mode,
                'match_count': sum(
                    size * (size - 1) // 2 for size in group_sizes
                ),
            }
        )
        return Ok(preview)

    if preliminary_type == StageType.swiss:
        round_count = _get_swiss_round_count_for_threshold(swiss_threshold)
        preview.update(
            {
                'swiss_threshold': swiss_threshold,
                'round_count': round_count,
                'qualifier_count': main_stage_size,
            }
        )
        return Ok(preview)

    return Ok(preview)


def _resolve_stage_builder_stage_for_generation(
    stage: Stage,
    *,
    participant_count: int,
) -> Result[Stage, str]:
    if not _is_stage_builder_v1_preliminary_stage(stage):
        return Ok(stage)

    main_stage_size = _get_stage_builder_main_stage_size(stage)
    if main_stage_size is None:
        return Err('Ungültige Größe der Main Stage im Baukasten.')

    if participant_count <= main_stage_size:
        return Err(
            'Vorrunde ist mit der aktuellen Anzahl ready Teilnehmer nicht nötig.'
        )

    if stage.type == StageType.round_robin_groups:
        plan_result = _resolve_round_robin_builder_plan(
            participant_count=participant_count,
            main_stage_size=main_stage_size,
            round_robin_builder_mode=stage.settings.get(
                'builder_round_robin_mode'
            ),
            round_robin_group_count=stage.settings.get(
                'builder_round_robin_group_count'
            ),
        )
        if plan_result.is_err():
            return Err(plan_result.unwrap_err())

        plan = plan_result.unwrap()
        resolved_settings = dict(stage.settings)
        resolved_settings['group_count'] = plan.group_count
        resolved_settings['builder_resolved_qualifiers_per_group'] = (
            plan.qualifiers_per_group
        )
        resolved_settings['builder_resolved_group_size_min'] = (
            plan.min_group_size
        )
        resolved_settings['builder_resolved_group_size_max'] = (
            plan.max_group_size
        )
        return Ok(
            Stage(
                id=stage.id,
                tournament_id=stage.tournament_id,
                order_no=stage.order_no,
                type=stage.type,
                name=stage.name,
                settings=resolved_settings,
                status=stage.status,
            )
        )

    if stage.type == StageType.swiss:
        threshold = _get_swiss_threshold_for_stage(
            stage, participant_count=participant_count
        )
        if threshold not in SWISS_THRESHOLDS and participant_count > 1:
            return Err('Ungültige Swiss-Schwelle.')
        return Ok(stage)

    return Ok(stage)

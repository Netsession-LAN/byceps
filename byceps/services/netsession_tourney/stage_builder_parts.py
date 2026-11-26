"""
byceps.services.netsession_tourney.stage_builder_parts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Building blocks of the stage builder: checking the input, the settings of
preliminary and main stage, and the audit log of the created stages.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from byceps.services.user.models import User

from .dbmodels import DbNetsessionTourneyStage
from .models import StageType
from .result_report_mode import RESULT_REPORT_MODE_ADMIN_ONLY
from .service_helpers import append_audit_log
from .stage_builder_settings import (
    STAGE_BUILDER_KIND_V1,
    STAGE_BUILDER_MAIN_STAGE_SIZES,
)
from .swiss_thresholds import (
    get_swiss_round_count_for_threshold,
    SWISS_THRESHOLDS,
)


DUEL_MAIN_STAGE_TYPES = {
    StageType.single_elimination,
    StageType.double_elimination,
    StageType.double_elimination_double_grand_final,
}
DUEL_PRELIMINARY_TYPES = {None, StageType.round_robin_groups, StageType.swiss}


@dataclass(frozen=True, kw_only=True)
class StageTiming:
    match_duration_minutes: int | None
    max_matches_per_round: int | None
    break_between_rounds_minutes: int | None

    def validate(self) -> str | None:
        if self.match_duration_minutes is not None and not (
            1 <= self.match_duration_minutes <= 240
        ):
            return 'Ungültige Matchdauer.'
        if self.max_matches_per_round is not None and not (
            1 <= self.max_matches_per_round <= 256
        ):
            return 'Ungültige Höchstzahl an Matches pro Runde.'
        if self.break_between_rounds_minutes is not None and not (
            0 <= self.break_between_rounds_minutes <= 240
        ):
            return 'Ungültige Pause zwischen den Runden.'
        return None

    def settings(self) -> dict[str, int]:
        """Only the values that were given."""
        values = {
            'match_duration_minutes': self.match_duration_minutes,
            'max_matches_per_round': self.max_matches_per_round,
            'break_between_rounds_minutes': self.break_between_rounds_minutes,
        }
        return {
            key: value for key, value in values.items() if value is not None
        }


def validate_duel_builder_input(
    *,
    main_stage_type: StageType,
    main_stage_size: int,
    generation_basis: str,
    preliminary_type: StageType | None,
    round_robin_builder_mode: str | None,
    round_robin_group_count: int | None,
    swiss_threshold: int | None,
    timing: StageTiming,
) -> str | None:
    """Return an error message, or `None` if the input is fine."""
    structure_error = _validate_duel_builder_structure(
        main_stage_type=main_stage_type,
        main_stage_size=main_stage_size,
        generation_basis=generation_basis,
        preliminary_type=preliminary_type,
    )
    if structure_error is not None:
        return structure_error

    if preliminary_type == StageType.round_robin_groups:
        round_robin_error = _validate_round_robin_builder_options(
            round_robin_builder_mode, round_robin_group_count
        )
        if round_robin_error is not None:
            return round_robin_error

    if (
        preliminary_type == StageType.swiss
        and swiss_threshold not in SWISS_THRESHOLDS
    ):
        return 'Für eine Swiss-Vorrunde bitte eine gültige Schwelle wählen.'

    return timing.validate()


def _validate_duel_builder_structure(
    *,
    main_stage_type: StageType,
    main_stage_size: int,
    generation_basis: str,
    preliminary_type: StageType | None,
) -> str | None:
    if main_stage_type not in DUEL_MAIN_STAGE_TYPES:
        return 'Dieser Typ des Hauptturniers wird vom Turnierplaner nicht unterstützt.'
    if main_stage_size not in STAGE_BUILDER_MAIN_STAGE_SIZES:
        return 'Ungültige Größe des Hauptturniers.'
    if generation_basis != 'ready':
        return 'Ungültige Grundlage für die Erzeugung.'
    if preliminary_type not in DUEL_PRELIMINARY_TYPES:
        return 'Dieser Vorrunden-Typ wird vom Baukasten nicht unterstützt.'
    return None


def _validate_round_robin_builder_options(
    round_robin_builder_mode: str | None,
    round_robin_group_count: int | None,
) -> str | None:
    if round_robin_builder_mode not in {
        None,
        'standard',
        'manual_group_count',
    }:
        return 'Ungültige Round-Robin-Strategie.'
    if round_robin_builder_mode == 'manual_group_count' and (
        round_robin_group_count is None or round_robin_group_count < 2
    ):
        return 'Für die Expertenoption muss eine gültige Gruppenzahl gewählt werden.'
    return None


def duel_preliminary_settings(
    *,
    preliminary_type: StageType,
    generation_basis: str,
    main_stage_size: int,
    round_robin_builder_mode: str | None,
    round_robin_group_count: int | None,
    swiss_threshold: int | None,
    timing: StageTiming,
) -> dict[str, Any]:
    settings: dict[str, Any] = {
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
        settings['swiss_threshold'] = swiss_threshold
        settings['round_count'] = get_swiss_round_count_for_threshold(
            swiss_threshold
        )
    elif preliminary_type == StageType.round_robin_groups:
        settings['builder_round_robin_mode'] = (
            round_robin_builder_mode or 'standard'
        )
        if round_robin_group_count is not None:
            settings['builder_round_robin_group_count'] = (
                round_robin_group_count
            )
    settings.update(timing.settings())
    return settings


def duel_main_stage_settings(
    *,
    generation_basis: str,
    main_stage_size: int,
    preliminary_stage: DbNetsessionTourneyStage | None,
    preliminary_type: StageType | None,
    timing: StageTiming,
) -> dict[str, Any]:
    settings: dict[str, Any] = {
        'builder_kind': STAGE_BUILDER_KIND_V1,
        'builder_role': 'main',
        'builder_generation_basis': generation_basis,
        'builder_main_stage_size': main_stage_size,
        'result_report_mode': 'both_must_confirm',
    }
    if preliminary_stage is None:
        settings['participant_source_mode'] = 'tournament'
    else:
        settings['participant_source_mode'] = 'stage_qualifiers'
        settings['qualifier_source_stage_ids'] = [str(preliminary_stage.id)]
        settings['qualifier_selection_mode'] = (
            'per_group'
            if preliminary_type == StageType.round_robin_groups
            else 'per_stage'
        )
        settings['qualifier_top_n'] = (
            main_stage_size if preliminary_type == StageType.swiss else 1
        )
        settings['builder_auto_qualifier_count'] = True
        settings['builder_preliminary_stage_id'] = str(preliminary_stage.id)
    settings.update(timing.settings())
    return settings


def audit_created_stages(
    created_stages: list[DbNetsessionTourneyStage],
    initiator: User,
    now: datetime,
) -> None:
    for created_stage in created_stages:
        append_audit_log(
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

"""
byceps.services.netsession_tourney.stage_form_choices
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage type choices for the stage form.
"""

from __future__ import annotations

from .enum_labels import stage_type_display_name
from .models import (
    RegistrationMode,
    StageFamily,
    StageTypeSpec,
    TournamentMode,
)
from .registration_validation import (
    is_stage_type_compatible_with_registration_mode,
)
from .stage_service import get_available_stage_type_specs


def build_stage_form_type_choices(
    tournament_mode: TournamentMode | None,
    registration_mode: str | None,
) -> list[tuple[str, str]]:
    specs = get_available_stage_type_specs()
    if tournament_mode is not None:
        specs = _filter_stage_type_specs_by_family(specs, tournament_mode)
    if registration_mode is not None:
        specs = _filter_stage_type_specs_by_registration_mode(
            specs, registration_mode
        )

    return [
        (spec.type.value, _build_stage_type_choice_label(spec))
        for spec in specs
        if spec.enabled
    ]


def _filter_stage_type_specs_by_family(
    specs: list[StageTypeSpec], tournament_mode: TournamentMode
) -> list[StageTypeSpec]:
    expected_family = (
        StageFamily.duel
        if tournament_mode == TournamentMode.duel
        else StageFamily.ffa
    )
    return [spec for spec in specs if spec.family == expected_family]


def _filter_stage_type_specs_by_registration_mode(
    specs: list[StageTypeSpec], registration_mode: str
) -> list[StageTypeSpec]:
    tournament_registration_mode = RegistrationMode(registration_mode)
    return [
        spec
        for spec in specs
        if is_stage_type_compatible_with_registration_mode(
            spec.type,
            tournament_registration_mode,
        )
    ]


def _build_stage_type_choice_label(spec: StageTypeSpec) -> str:
    if not spec.publishable:
        return f'{stage_type_display_name(spec.type)} (disabled/beta)'
    return stage_type_display_name(spec.type)

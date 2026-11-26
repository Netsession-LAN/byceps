"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_wizard_forms
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Forms of the stage builder (Turnierplaner) wizard steps.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.blueprints.admin.stage_builder_wizard_state import (
    get_stage_builder_default_main_stage_size,
    is_ffa_stage_builder_tournament,
)
from byceps.services.netsession_tourney.forms import (
    StageBuilderMainForm,
    StageBuilderPreliminaryForm,
    StageBuilderTimingForm,
)
from byceps.services.netsession_tourney.models import (
    StageType,
)


def build_stage_builder_main_form(
    *,
    tournament,
    state: dict,
    erroneous_form: StageBuilderMainForm | None = None,
) -> StageBuilderMainForm:
    if erroneous_form is not None:
        return erroneous_form

    return StageBuilderMainForm(
        tournament_mode=tournament.mode,
        data={
            'generation_basis': state.get('generation_basis') or 'ready',
            'main_stage_type': state.get('main_stage_type')
            or (
                StageType.ffa_single_elimination.value
                if is_ffa_stage_builder_tournament(tournament)
                else StageType.double_elimination.value
            ),
            'main_stage_size': state.get('main_stage_size')
            or get_stage_builder_default_main_stage_size(tournament),
            'max_players_per_match': state.get('max_players_per_match') or 8,
        },
    )


def build_stage_builder_preliminary_form(
    *,
    tournament,
    state: dict,
    erroneous_form: StageBuilderPreliminaryForm | None = None,
) -> StageBuilderPreliminaryForm:
    if erroneous_form is not None:
        return erroneous_form

    main_stage_type = _parse_state_main_stage_type(state)

    return StageBuilderPreliminaryForm(
        tournament_mode=tournament.mode,
        main_stage_type=main_stage_type,
        data={
            'use_preliminary': state.get('use_preliminary', True),
            'preliminary_type': state.get('preliminary_type')
            or _get_default_preliminary_type(tournament, main_stage_type),
            'round_robin_builder_mode': (
                state.get('round_robin_builder_mode') or 'standard'
            ),
            'round_robin_group_count': state.get('round_robin_group_count'),
            'swiss_threshold': state.get('swiss_threshold') or 3,
        },
    )


def _parse_state_main_stage_type(state: dict) -> StageType | None:
    raw_main_stage_type = state.get('main_stage_type')
    if not raw_main_stage_type:
        return None

    try:
        return StageType(raw_main_stage_type)
    except ValueError:
        return None


def _get_default_preliminary_type(
    tournament, main_stage_type: StageType | None
) -> str:
    if main_stage_type == StageType.ffa_flatout2_single_elimination:
        return StageType.ffa_flatout2_single_elimination.value

    return (
        StageType.ffa_single_elimination.value
        if is_ffa_stage_builder_tournament(tournament)
        else StageType.round_robin_groups.value
    )


def build_stage_builder_timing_form(
    *, state: dict, erroneous_form: StageBuilderTimingForm | None = None
) -> StageBuilderTimingForm:
    if erroneous_form is not None:
        return erroneous_form

    return StageBuilderTimingForm(
        data={
            'match_duration_minutes': state.get('match_duration_minutes'),
            'max_matches_per_round': state.get('max_matches_per_round'),
            'break_between_rounds_minutes': state.get(
                'break_between_rounds_minutes', 0
            ),
        }
    )

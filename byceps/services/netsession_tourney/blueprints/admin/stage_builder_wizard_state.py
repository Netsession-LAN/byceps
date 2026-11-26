"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_wizard_state
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Progress of the stage builder (Turnierplaner) wizard: which steps
are complete, and the preview on its review step.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.blueprints.admin.stage_builder_review_lines import (
    build_review_preview_lines,
    parse_review_plan_arguments,
)
from byceps.services.netsession_tourney.models import (
    StageType,
    TournamentMode,
)
from byceps.services.netsession_tourney.stage_builder_preview import (
    preview_stage_builder_plan,
)
from byceps.services.netsession_tourney.stage_builder_settings import (
    STAGE_BUILDER_MAIN_STAGE_SIZES,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)
from byceps.services.party.models import Party
from byceps.util.framework.flash import flash_error
from byceps.util.views import redirect_to


def is_stage_builder_main_complete(state: dict) -> bool:
    if not all(
        (
            state.get('generation_basis'),
            state.get('main_stage_type'),
            state.get('main_stage_size'),
        )
    ):
        return False

    if state.get('main_stage_type') in {
        StageType.ffa_single_elimination.value,
        StageType.ffa_flatout2_single_elimination.value,
    }:
        return state.get('max_players_per_match') is not None

    return bool(state.get('main_stage_size'))


def is_stage_builder_preliminary_complete(state: dict) -> bool:
    if 'use_preliminary' not in state:
        return False

    if not state.get('use_preliminary'):
        return True

    preliminary_type = state.get('preliminary_type')
    if not preliminary_type:
        return False

    if (
        preliminary_type == StageType.round_robin_groups.value
        and state.get('round_robin_builder_mode') == 'manual_group_count'
    ):
        return state.get('round_robin_group_count') is not None

    if preliminary_type != StageType.swiss.value:
        return True

    return state.get('swiss_threshold') is not None


def is_ffa_stage_builder_tournament(tournament) -> bool:
    return tournament.mode == TournamentMode.ffa


def get_stage_builder_default_main_stage_size(tournament) -> str:
    participant_limit = tournament.participant_limit
    if participant_limit is not None:
        for allowed_size in sorted(STAGE_BUILDER_MAIN_STAGE_SIZES):
            if allowed_size >= participant_limit:
                return str(allowed_size)

    return '64'  # no limit set: a sensible start, the admin adjusts it


def is_stage_builder_timing_complete(state: dict) -> bool:
    return 'break_between_rounds_minutes' in state


def stage_builder_steps() -> list[dict[str, str]]:
    return [
        {'id': 'main', 'number': '1', 'label': gettext('Hauptturnier')},
        {'id': 'preliminary', 'number': '2', 'label': gettext('Vorrunde')},
        {'id': 'timing', 'number': '3', 'label': gettext('Zeitplan')},
        {'id': 'review', 'number': '4', 'label': gettext('Prüfen')},
    ]


def assert_tournament_has_no_stages_for_builder_or_redirect(
    party: Party, tournament
):
    stages = get_stages_for_tournament(party.id, tournament.id)
    if stages:
        flash_error(
            gettext(
                'Der Turnierplaner arbeitet nur auf Turnieren ohne vorhandene Phasen.'
            )
        )
        return redirect_to(
            '.view',
            party_id=party.id,
            tournament_id=tournament.id,
            tab='stages',
        )

    return None


def build_stage_builder_review_preview(
    party: Party, tournament, *, state: dict
) -> dict | None:
    if not is_stage_builder_main_complete(state):
        return None

    plan_arguments = parse_review_plan_arguments(state)
    if plan_arguments is None:
        return None

    main_stage_type, main_stage_size, preliminary_type = plan_arguments

    preview_result = preview_stage_builder_plan(
        party.id,
        tournament.id,
        generation_basis=str(state.get('generation_basis') or ''),
        main_stage_type=main_stage_type,
        main_stage_size=main_stage_size,
        max_players_per_match=state.get('max_players_per_match'),
        preliminary_type=preliminary_type,
        round_robin_builder_mode=state.get('round_robin_builder_mode'),
        round_robin_group_count=state.get('round_robin_group_count'),
        swiss_threshold=state.get('swiss_threshold'),
    )
    if preview_result.is_err():
        return {
            'title': gettext('Aktuelle Vorschau des Turnierplaners'),
            'error': preview_result.unwrap_err(),
        }

    preview = preview_result.unwrap()
    lines = build_review_preview_lines(
        preview, main_stage_type, main_stage_size, preliminary_type
    )

    return {
        'title': gettext('Aktuelle Vorschau des Turnierplaners'),
        'lines': lines,
    }

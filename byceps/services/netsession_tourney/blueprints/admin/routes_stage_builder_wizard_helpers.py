"""
byceps.services.netsession_tourney.blueprints.admin.routes_stage_builder_wizard_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Helpers for the stage builder (Turnierplaner) wizard routes in
`routes_stage_management`: step guards, default state and the state
updates from the step forms.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import Any

from flask_babel import gettext
from werkzeug.wrappers import Response

from byceps.services.netsession_tourney.blueprints.admin.stage_builder_wizard_state import (
    assert_tournament_has_no_stages_for_builder_or_redirect,
    get_stage_builder_default_main_stage_size,
    is_ffa_stage_builder_tournament,
    is_stage_builder_main_complete,
    is_stage_builder_preliminary_complete,
    is_stage_builder_timing_complete,
)
from byceps.services.netsession_tourney.blueprints.admin.wizard_helpers import (
    get_stage_builder_wizard_state,
)
from byceps.services.netsession_tourney.models import StageType
from byceps.services.party.models import Party
from byceps.util.views import redirect_to


_WIZARD_STEP_CHECKS = (
    ('.stage_builder_wizard_main', is_stage_builder_main_complete),
    (
        '.stage_builder_wizard_preliminary',
        is_stage_builder_preliminary_complete,
    ),
    ('.stage_builder_wizard_timing', is_stage_builder_timing_complete),
)


def redirect_to_wizard_step(
    endpoint: str, party: Party, tournament: Any
) -> Response:
    return redirect_to(
        endpoint,
        party_id=party.id,
        tournament_id=tournament.id,
    )


def load_stage_builder_wizard_state(
    party: Party, tournament: Any, *, completed_steps: int
) -> tuple[dict | None, Response | None]:
    """Return the wizard state, or a redirect if the tournament already
    has stages or one of the first `completed_steps` steps is missing."""
    redirect_response = assert_tournament_has_no_stages_for_builder_or_redirect(
        party, tournament
    )
    if redirect_response is not None:
        return None, redirect_response

    state = get_stage_builder_wizard_state(party.id, tournament.id)
    for endpoint, is_complete in _WIZARD_STEP_CHECKS[:completed_steps]:
        if not is_complete(state):
            return state, redirect_to_wizard_step(endpoint, party, tournament)

    return state, None


def build_default_main_state(tournament: Any) -> dict[str, Any]:
    if is_ffa_stage_builder_tournament(tournament):
        return {
            'generation_basis': 'ready',
            'main_stage_type': StageType.ffa_single_elimination.value,
            'main_stage_size': get_stage_builder_default_main_stage_size(
                tournament
            ),
            'max_players_per_match': 8,
            'use_preliminary': False,
            'preliminary_type': '',
            'round_robin_builder_mode': None,
            'round_robin_group_count': None,
            'swiss_threshold': None,
            'break_between_rounds_minutes': 0,
        }

    return {
        'generation_basis': 'ready',
        'main_stage_type': StageType.double_elimination.value,
        'main_stage_size': '16',
        'max_players_per_match': None,
        'use_preliminary': True,
        'preliminary_type': StageType.round_robin_groups.value,
        'round_robin_builder_mode': 'standard',
        'round_robin_group_count': None,
        'swiss_threshold': 3,
        'break_between_rounds_minutes': 0,
    }


def has_ffa_main_form_errors(tournament: Any, form: Any) -> bool:
    """Add FFA-specific errors to the main step form; return whether
    there were any."""
    if not is_ffa_stage_builder_tournament(tournament):
        return False

    if form.max_players_per_match.data is None:
        form.max_players_per_match.errors.append(
            gettext('Bitte eine gültige Heat-Größe angeben.')
        )
        return True

    if (
        form.main_stage_type.data
        == StageType.ffa_flatout2_single_elimination.value
        and form.max_players_per_match.data not in {6, 7, 8}
    ):
        form.max_players_per_match.errors.append(
            gettext('FlatOut 2 erlaubt hier nur 6, 7 oder 8 Teilnehmer.')
        )
        return True

    return False


def apply_main_form_to_state(state: dict, form: Any) -> None:
    state.update(
        {
            'generation_basis': str(form.generation_basis.data or '').strip(),
            'main_stage_type': str(form.main_stage_type.data or '').strip(),
            'main_stage_size': str(form.main_stage_size.data or '').strip(),
            'max_players_per_match': form.max_players_per_match.data,
        }
    )


def build_preliminary_state_update(
    tournament: Any, form: Any
) -> dict[str, Any]:
    if is_ffa_stage_builder_tournament(tournament):
        return _build_ffa_preliminary_state_update(form)

    return _build_duel_preliminary_state_update(form)


def _build_ffa_preliminary_state_update(form: Any) -> dict[str, Any]:
    use_preliminary = bool(form.use_preliminary.data)
    return {
        'use_preliminary': use_preliminary,
        'preliminary_type': (
            str(form.preliminary_type.data or '').strip()
            if use_preliminary
            else ''
        ),
        'round_robin_builder_mode': None,
        'round_robin_group_count': None,
        'swiss_threshold': None,
    }


def _build_duel_preliminary_state_update(form: Any) -> dict[str, Any]:
    use_preliminary = bool(form.use_preliminary.data)
    return {
        'use_preliminary': use_preliminary,
        'preliminary_type': str(form.preliminary_type.data or '').strip()
        if use_preliminary
        else '',
        'round_robin_builder_mode': (
            str(form.round_robin_builder_mode.data or '').strip()
            if use_preliminary
            else None
        ),
        'round_robin_group_count': (
            form.round_robin_group_count.data if use_preliminary else None
        ),
        'swiss_threshold': (
            form.swiss_threshold.data if use_preliminary else None
        ),
    }


def build_timing_state_update(form: Any) -> dict[str, Any]:
    return {
        'match_duration_minutes': form.match_duration_minutes.data,
        'max_matches_per_round': form.max_matches_per_round.data,
        'break_between_rounds_minutes': (
            form.break_between_rounds_minutes.data or 0
        ),
    }

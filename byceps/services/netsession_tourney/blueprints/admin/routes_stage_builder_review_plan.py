"""
byceps.services.netsession_tourney.blueprints.admin.routes_stage_builder_review_plan
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Helpers for submitting the review step of the stage builder
(Turnierplaner) wizard in `routes_stage_management`: read the plan
arguments from the wizard state and handle the result of building the
plan.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import Any

from flask_babel import gettext
from werkzeug.wrappers import Response

from byceps.services.netsession_tourney.blueprints.admin.wizard_helpers import (
    clear_stage_builder_wizard_state,
)
from byceps.services.netsession_tourney.models import StageType
from byceps.services.party.models import Party
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.result import Err, Ok, Result
from byceps.util.views import redirect_to


_MAIN_STEP = '.stage_builder_wizard_main'
_PRELIMINARY_STEP = '.stage_builder_wizard_preliminary'

# An error is a message to flash and the wizard step endpoint to return to.
type ReviewPlanError = tuple[str, str]


def parse_review_plan_kwargs(
    state: dict,
) -> Result[dict[str, Any], ReviewPlanError]:
    """Return the plan arguments taken from the wizard state."""
    try:
        generation_basis = str(state.get('generation_basis') or '').strip()
        main_stage_type = StageType(state['main_stage_type'])
        main_stage_size = int(state['main_stage_size'])
    except KeyError, TypeError, ValueError:
        return Err((gettext('Ungültige Daten des Turnierplaners.'), _MAIN_STEP))

    max_players_result = _parse_max_players_per_match(state)
    if max_players_result.is_err():
        return Err(max_players_result.unwrap_err())

    preliminary_result = _parse_preliminary(state)
    if preliminary_result.is_err():
        return Err(preliminary_result.unwrap_err())

    preliminary_type, swiss_threshold = preliminary_result.unwrap()
    return Ok(
        {
            'generation_basis': generation_basis,
            'main_stage_type': main_stage_type,
            'main_stage_size': main_stage_size,
            'max_players_per_match': max_players_result.unwrap(),
            'preliminary_type': preliminary_type,
            'round_robin_builder_mode': state.get('round_robin_builder_mode'),
            'round_robin_group_count': state.get('round_robin_group_count'),
            'swiss_threshold': swiss_threshold,
            'match_duration_minutes': state.get('match_duration_minutes'),
            'max_matches_per_round': state.get('max_matches_per_round'),
            'break_between_rounds_minutes': state.get(
                'break_between_rounds_minutes'
            ),
        }
    )


def _parse_max_players_per_match(
    state: dict,
) -> Result[int | None, ReviewPlanError]:
    max_players_per_match = state.get('max_players_per_match')
    if max_players_per_match in {'', None}:
        return Ok(None)

    try:
        return Ok(int(max_players_per_match))
    except TypeError, ValueError:
        return Err(
            (
                gettext('Ungültige Matchgröße für den Turnierplaner.'),
                _MAIN_STEP,
            )
        )


def _parse_preliminary(
    state: dict,
) -> Result[tuple[StageType | None, Any], ReviewPlanError]:
    """Return preliminary type and Swiss threshold."""
    if not state.get('use_preliminary'):
        return Ok((None, None))

    raw_preliminary_type = str(state.get('preliminary_type') or '').strip()
    if not raw_preliminary_type:
        return Err(
            (
                gettext('Bitte ein Vorrundenformat auswählen.'),
                _PRELIMINARY_STEP,
            )
        )

    try:
        preliminary_type = StageType(raw_preliminary_type)
    except ValueError:
        return Err((gettext('Ungültiges Vorrundenformat.'), _PRELIMINARY_STEP))

    if preliminary_type != StageType.swiss:
        return Ok((preliminary_type, None))

    return _parse_swiss_threshold(state).map(
        lambda swiss_threshold: (preliminary_type, swiss_threshold)
    )


def _parse_swiss_threshold(state: dict) -> Result[Any, ReviewPlanError]:
    swiss_threshold = state.get('swiss_threshold')
    if swiss_threshold not in {2, 3, 4}:
        return Err(
            (
                gettext('Swiss-Vorrunden benötigen eine gültige Schwelle.'),
                _PRELIMINARY_STEP,
            )
        )

    return Ok(swiss_threshold)


def handle_stage_builder_plan_result(
    result: Result[list, str], party: Party, tournament: Any
) -> Response | None:
    match result:
        case Ok(created_stages):
            clear_stage_builder_wizard_state(party.id, tournament.id)
            flash_success(
                gettext(
                    'Phasenplan wurde erstellt. %(count)s Phasen angelegt.',
                    count=len(created_stages),
                )
            )
            selected_stage_id = (
                created_stages[-1].id if created_stages else None
            )
            return redirect_to(
                '.view',
                party_id=party.id,
                tournament_id=tournament.id,
                tab='stages',
                stage_id=selected_stage_id,
            )
        case Err(message):
            flash_error(message)
            return redirect_to(
                '.stage_builder_wizard_review',
                party_id=party.id,
                tournament_id=tournament.id,
            )

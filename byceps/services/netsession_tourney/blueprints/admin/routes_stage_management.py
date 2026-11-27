"""
byceps.services.netsession_tourney.blueprints.admin.routes_stage_management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import g, request

from byceps.services.netsession_tourney.blueprints.admin.result_helpers import (
    _get_tournament_or_404,
    get_party_or_404,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_stage_actions import (
    register_stage_builder_review_routes,
    register_stage_builder_start_routes,
    register_stage_delete_routes,
    register_stage_participant_source_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_stage_builder_review_plan import (
    handle_stage_builder_plan_result,
    parse_review_plan_kwargs,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_stage_builder_wizard_helpers import (
    apply_main_form_to_state,
    build_default_main_state,
    build_preliminary_state_update,
    build_timing_state_update,
    has_ffa_main_form_errors,
    load_stage_builder_wizard_state,
    redirect_to_wizard_step,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_stage_form import (
    register_stage_create_routes,
    register_stage_update_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_stage_form_helpers import (
    stage_type_or_none,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_stage_generation import (
    register_stage_generation_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_wizard_forms import (
    build_stage_builder_main_form,
    build_stage_builder_preliminary_form,
    build_stage_builder_timing_form,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_wizard_state import (
    is_ffa_stage_builder_tournament,
    stage_builder_steps,
)
from byceps.services.netsession_tourney.blueprints.admin.wizard_helpers import (
    set_stage_builder_wizard_state,
)
from byceps.services.netsession_tourney.forms import (
    StageBuilderMainForm,
    StageBuilderPreliminaryForm,
    StageBuilderTimingForm,
)
from byceps.services.netsession_tourney.stage_builder_service import (
    build_stage_builder_plan,
)
from byceps.util.framework.flash import flash_error
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.views import permission_required


def register(blueprint):
    register_stage_builder_start_routes(blueprint)
    for rule, view_func, method in _WIZARD_ROUTES:
        blueprint.add_url_rule(
            rule,
            endpoint=view_func.__name__,
            view_func=view_func,
            methods=[method],
        )
    register_stage_builder_review_routes(blueprint)
    register_stage_create_routes(blueprint)
    register_stage_generation_routes(blueprint)
    register_stage_update_routes(blueprint)
    register_stage_participant_source_routes(blueprint)
    register_stage_delete_routes(blueprint)


@permission_required('netsession_tourney.manage')
@templated('admin/netsession_tourney/stage_builder/main')
def stage_builder_wizard_main(party_id, tournament_id, erroneous_form=None):
    party = get_party_or_404(party_id)
    tournament = _get_tournament_or_404(party.id, tournament_id)
    state, redirect_response = load_stage_builder_wizard_state(
        party, tournament, completed_steps=0
    )
    if redirect_response is not None:
        return redirect_response

    if not state:
        state = build_default_main_state(tournament)

    return {
        'party': party,
        'tournament': tournament,
        'form': build_stage_builder_main_form(
            tournament=tournament,
            state=state,
            erroneous_form=erroneous_form,
        ),
        'wizard_step': 'main',
        'wizard_steps': stage_builder_steps(),
        'is_ffa_builder': is_ffa_stage_builder_tournament(tournament),
    }


@permission_required('netsession_tourney.manage')
def stage_builder_wizard_main_submit(party_id, tournament_id):
    party = get_party_or_404(party_id)
    tournament = _get_tournament_or_404(party.id, tournament_id)
    state, redirect_response = load_stage_builder_wizard_state(
        party, tournament, completed_steps=0
    )
    if redirect_response is not None:
        return redirect_response

    form = build_stage_builder_main_form(
        tournament=tournament,
        state=state,
        erroneous_form=StageBuilderMainForm(
            request.form,
            tournament_mode=tournament.mode,
        ),
    )
    if not form.validate() or has_ffa_main_form_errors(tournament, form):
        return stage_builder_wizard_main(
            party.id, tournament.id, erroneous_form=form
        )

    apply_main_form_to_state(state, form)
    set_stage_builder_wizard_state(party.id, tournament.id, state)
    return redirect_to_wizard_step(
        '.stage_builder_wizard_preliminary', party, tournament
    )


@permission_required('netsession_tourney.manage')
@templated('admin/netsession_tourney/stage_builder/preliminary')
def stage_builder_wizard_preliminary(
    party_id, tournament_id, erroneous_form=None
):
    party = get_party_or_404(party_id)
    tournament = _get_tournament_or_404(party.id, tournament_id)
    state, redirect_response = load_stage_builder_wizard_state(
        party, tournament, completed_steps=1
    )
    if redirect_response is not None:
        return redirect_response

    supports_preliminary_builder = True

    return {
        'party': party,
        'tournament': tournament,
        'form': build_stage_builder_preliminary_form(
            tournament=tournament,
            state=state,
            erroneous_form=erroneous_form,
        ),
        'wizard_step': 'preliminary',
        'wizard_steps': stage_builder_steps(),
        'supports_preliminary_builder': supports_preliminary_builder,
    }


@permission_required('netsession_tourney.manage')
def stage_builder_wizard_preliminary_submit(party_id, tournament_id):
    party = get_party_or_404(party_id)
    tournament = _get_tournament_or_404(party.id, tournament_id)
    state, redirect_response = load_stage_builder_wizard_state(
        party, tournament, completed_steps=1
    )
    if redirect_response is not None:
        return redirect_response

    form = build_stage_builder_preliminary_form(
        tournament=tournament,
        state=state,
        erroneous_form=StageBuilderPreliminaryForm(
            request.form,
            tournament_mode=tournament.mode,
            main_stage_type=stage_type_or_none(state.get('main_stage_type')),
        ),
    )
    if not form.validate():
        return stage_builder_wizard_preliminary(
            party.id, tournament.id, erroneous_form=form
        )

    state.update(build_preliminary_state_update(tournament, form))
    set_stage_builder_wizard_state(party.id, tournament.id, state)
    return redirect_to_wizard_step(
        '.stage_builder_wizard_timing', party, tournament
    )


@permission_required('netsession_tourney.manage')
@templated('admin/netsession_tourney/stage_builder/timing')
def stage_builder_wizard_timing(party_id, tournament_id, erroneous_form=None):
    party = get_party_or_404(party_id)
    tournament = _get_tournament_or_404(party.id, tournament_id)
    state, redirect_response = load_stage_builder_wizard_state(
        party, tournament, completed_steps=2
    )
    if redirect_response is not None:
        return redirect_response

    return {
        'party': party,
        'tournament': tournament,
        'form': build_stage_builder_timing_form(
            state=state,
            erroneous_form=erroneous_form,
        ),
        'wizard_step': 'timing',
        'wizard_steps': stage_builder_steps(),
    }


@permission_required('netsession_tourney.manage')
def stage_builder_wizard_timing_submit(party_id, tournament_id):
    party = get_party_or_404(party_id)
    tournament = _get_tournament_or_404(party.id, tournament_id)
    state, redirect_response = load_stage_builder_wizard_state(
        party, tournament, completed_steps=2
    )
    if redirect_response is not None:
        return redirect_response

    form = build_stage_builder_timing_form(
        state=state,
        erroneous_form=StageBuilderTimingForm(request.form),
    )
    if not form.validate():
        return stage_builder_wizard_timing(
            party.id, tournament.id, erroneous_form=form
        )

    state.update(build_timing_state_update(form))
    set_stage_builder_wizard_state(party.id, tournament.id, state)
    return redirect_to_wizard_step(
        '.stage_builder_wizard_review', party, tournament
    )


@permission_required('netsession_tourney.manage')
def stage_builder_wizard_review_submit(party_id, tournament_id):
    party = get_party_or_404(party_id)
    tournament = _get_tournament_or_404(party.id, tournament_id)
    state, redirect_response = load_stage_builder_wizard_state(
        party, tournament, completed_steps=3
    )
    if redirect_response is not None:
        return redirect_response

    match parse_review_plan_kwargs(state):
        case Err((message, step_endpoint)):
            flash_error(message)
            return redirect_to_wizard_step(step_endpoint, party, tournament)
        case Ok(plan_kwargs):
            return handle_stage_builder_plan_result(
                build_stage_builder_plan(
                    party.id,
                    tournament.id,
                    **plan_kwargs,
                    initiator=g.user.as_user(),
                ),
                party,
                tournament,
            )


_WIZARD_URL = (
    '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder'
)

# (URL, view, HTTP method); the endpoint is the view's name, as before.
_WIZARD_ROUTES = [
    (f'{_WIZARD_URL}/main', stage_builder_wizard_main, 'GET'),
    (f'{_WIZARD_URL}/main', stage_builder_wizard_main_submit, 'POST'),
    (f'{_WIZARD_URL}/preliminary', stage_builder_wizard_preliminary, 'GET'),
    (
        f'{_WIZARD_URL}/preliminary',
        stage_builder_wizard_preliminary_submit,
        'POST',
    ),
    (f'{_WIZARD_URL}/timing', stage_builder_wizard_timing, 'GET'),
    (f'{_WIZARD_URL}/timing', stage_builder_wizard_timing_submit, 'POST'),
    (f'{_WIZARD_URL}/review', stage_builder_wizard_review_submit, 'POST'),
]

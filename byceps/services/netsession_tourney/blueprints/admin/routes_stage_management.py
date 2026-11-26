"""
byceps.services.netsession_tourney.blueprints.admin.routes_stage_management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import g, request
from flask_babel import gettext

from byceps.services.netsession_tourney.blueprints.admin.routes_stage_actions import (
    register_stage_builder_review_routes,
    register_stage_builder_start_routes,
    register_stage_delete_routes,
    register_stage_participant_source_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_stage_form import (
    register_stage_create_routes,
    register_stage_update_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_stage_generation import (
    register_stage_generation_routes,
)
from byceps.services.netsession_tourney.forms import (
    StageBuilderMainForm,
    StageBuilderPreliminaryForm,
    StageBuilderTimingForm,
)
from byceps.services.netsession_tourney.models import (
    StageType,
)
from byceps.services.netsession_tourney.stage_builder_service import (
    build_stage_builder_plan,
)
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.views import permission_required, redirect_to

from .result_helpers import (
    _get_tournament_or_404,
    get_party_or_404,
)
from .stage_builder_wizard_forms import (
    build_stage_builder_main_form,
    build_stage_builder_preliminary_form,
    build_stage_builder_timing_form,
)
from .stage_builder_wizard_state import (
    assert_tournament_has_no_stages_for_builder_or_redirect,
    get_stage_builder_default_main_stage_size,
    is_ffa_stage_builder_tournament,
    is_stage_builder_main_complete,
    is_stage_builder_preliminary_complete,
    is_stage_builder_timing_complete,
    stage_builder_steps,
)
from .wizard_helpers import (
    clear_stage_builder_wizard_state,
    get_stage_builder_wizard_state,
    set_stage_builder_wizard_state,
)


def register(blueprint):
    register_stage_builder_start_routes(blueprint)

    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder/main'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/stage_builder/main')
    def stage_builder_wizard_main(party_id, tournament_id, erroneous_form=None):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        redirect_response = (
            assert_tournament_has_no_stages_for_builder_or_redirect(
                party, tournament
            )
        )
        if redirect_response is not None:
            return redirect_response

        state = get_stage_builder_wizard_state(party.id, tournament.id)
        if not state:
            if is_ffa_stage_builder_tournament(tournament):
                state = {
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
            else:
                state = {
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

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder/main'
    )
    @permission_required('netsession_tourney.manage')
    def stage_builder_wizard_main_submit(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        redirect_response = (
            assert_tournament_has_no_stages_for_builder_or_redirect(
                party, tournament
            )
        )
        if redirect_response is not None:
            return redirect_response

        state = get_stage_builder_wizard_state(party.id, tournament.id)
        form = build_stage_builder_main_form(
            tournament=tournament,
            state=state,
            erroneous_form=StageBuilderMainForm(
                request.form,
                tournament_mode=tournament.mode,
            ),
        )
        if not form.validate():
            return stage_builder_wizard_main(
                party.id, tournament.id, erroneous_form=form
            )

        if is_ffa_stage_builder_tournament(tournament):
            if form.max_players_per_match.data is None:
                form.max_players_per_match.errors.append(
                    gettext('Bitte eine gültige Heat-Größe angeben.')
                )
                return stage_builder_wizard_main(
                    party.id, tournament.id, erroneous_form=form
                )

            if (
                form.main_stage_type.data
                == StageType.ffa_flatout2_single_elimination.value
                and form.max_players_per_match.data not in {6, 7, 8}
            ):
                form.max_players_per_match.errors.append(
                    gettext(
                        'FlatOut 2 erlaubt hier nur 6, 7 oder 8 Teilnehmer.'
                    )
                )
                return stage_builder_wizard_main(
                    party.id, tournament.id, erroneous_form=form
                )

        state.update(
            {
                'generation_basis': str(
                    form.generation_basis.data or ''
                ).strip(),
                'main_stage_type': str(form.main_stage_type.data or '').strip(),
                'main_stage_size': str(form.main_stage_size.data or '').strip(),
                'max_players_per_match': form.max_players_per_match.data,
            }
        )
        set_stage_builder_wizard_state(party.id, tournament.id, state)
        return redirect_to(
            '.stage_builder_wizard_preliminary',
            party_id=party.id,
            tournament_id=tournament.id,
        )

    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder/preliminary'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/stage_builder/preliminary')
    def stage_builder_wizard_preliminary(
        party_id, tournament_id, erroneous_form=None
    ):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        redirect_response = (
            assert_tournament_has_no_stages_for_builder_or_redirect(
                party, tournament
            )
        )
        if redirect_response is not None:
            return redirect_response

        state = get_stage_builder_wizard_state(party.id, tournament.id)
        if not is_stage_builder_main_complete(state):
            return redirect_to(
                '.stage_builder_wizard_main',
                party_id=party.id,
                tournament_id=tournament.id,
            )

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

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder/preliminary'
    )
    @permission_required('netsession_tourney.manage')
    def stage_builder_wizard_preliminary_submit(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        redirect_response = (
            assert_tournament_has_no_stages_for_builder_or_redirect(
                party, tournament
            )
        )
        if redirect_response is not None:
            return redirect_response

        state = get_stage_builder_wizard_state(party.id, tournament.id)
        if not is_stage_builder_main_complete(state):
            return redirect_to(
                '.stage_builder_wizard_main',
                party_id=party.id,
                tournament_id=tournament.id,
            )

        form = build_stage_builder_preliminary_form(
            tournament=tournament,
            state=state,
            erroneous_form=StageBuilderPreliminaryForm(
                request.form,
                tournament_mode=tournament.mode,
                main_stage_type=(
                    StageType(state['main_stage_type'])
                    if state.get('main_stage_type')
                    in {stage_type.value for stage_type in StageType}
                    else None
                ),
            ),
        )
        if not form.validate():
            return stage_builder_wizard_preliminary(
                party.id, tournament.id, erroneous_form=form
            )

        if is_ffa_stage_builder_tournament(tournament):
            use_preliminary = bool(form.use_preliminary.data)
            state.update(
                {
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
            )
        else:
            use_preliminary = bool(form.use_preliminary.data)
            state.update(
                {
                    'use_preliminary': use_preliminary,
                    'preliminary_type': str(
                        form.preliminary_type.data or ''
                    ).strip()
                    if use_preliminary
                    else '',
                    'round_robin_builder_mode': (
                        str(form.round_robin_builder_mode.data or '').strip()
                        if use_preliminary
                        else None
                    ),
                    'round_robin_group_count': (
                        form.round_robin_group_count.data
                        if use_preliminary
                        else None
                    ),
                    'swiss_threshold': (
                        form.swiss_threshold.data if use_preliminary else None
                    ),
                }
            )
        set_stage_builder_wizard_state(party.id, tournament.id, state)
        return redirect_to(
            '.stage_builder_wizard_timing',
            party_id=party.id,
            tournament_id=tournament.id,
        )

    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder/timing'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/stage_builder/timing')
    def stage_builder_wizard_timing(
        party_id, tournament_id, erroneous_form=None
    ):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        redirect_response = (
            assert_tournament_has_no_stages_for_builder_or_redirect(
                party, tournament
            )
        )
        if redirect_response is not None:
            return redirect_response

        state = get_stage_builder_wizard_state(party.id, tournament.id)
        if not is_stage_builder_main_complete(state):
            return redirect_to(
                '.stage_builder_wizard_main',
                party_id=party.id,
                tournament_id=tournament.id,
            )
        if not is_stage_builder_preliminary_complete(state):
            return redirect_to(
                '.stage_builder_wizard_preliminary',
                party_id=party.id,
                tournament_id=tournament.id,
            )

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

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder/timing'
    )
    @permission_required('netsession_tourney.manage')
    def stage_builder_wizard_timing_submit(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        redirect_response = (
            assert_tournament_has_no_stages_for_builder_or_redirect(
                party, tournament
            )
        )
        if redirect_response is not None:
            return redirect_response

        state = get_stage_builder_wizard_state(party.id, tournament.id)
        if not is_stage_builder_main_complete(state):
            return redirect_to(
                '.stage_builder_wizard_main',
                party_id=party.id,
                tournament_id=tournament.id,
            )
        if not is_stage_builder_preliminary_complete(state):
            return redirect_to(
                '.stage_builder_wizard_preliminary',
                party_id=party.id,
                tournament_id=tournament.id,
            )

        form = build_stage_builder_timing_form(
            state=state,
            erroneous_form=StageBuilderTimingForm(request.form),
        )
        if not form.validate():
            return stage_builder_wizard_timing(
                party.id, tournament.id, erroneous_form=form
            )

        state.update(
            {
                'match_duration_minutes': form.match_duration_minutes.data,
                'max_matches_per_round': form.max_matches_per_round.data,
                'break_between_rounds_minutes': (
                    form.break_between_rounds_minutes.data or 0
                ),
            }
        )
        set_stage_builder_wizard_state(party.id, tournament.id, state)
        return redirect_to(
            '.stage_builder_wizard_review',
            party_id=party.id,
            tournament_id=tournament.id,
        )

    register_stage_builder_review_routes(blueprint)

    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/stages/builder/review'
    )
    @permission_required('netsession_tourney.manage')
    def stage_builder_wizard_review_submit(party_id, tournament_id):
        party = get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        redirect_response = (
            assert_tournament_has_no_stages_for_builder_or_redirect(
                party, tournament
            )
        )
        if redirect_response is not None:
            return redirect_response

        state = get_stage_builder_wizard_state(party.id, tournament.id)
        if not is_stage_builder_main_complete(state):
            return redirect_to(
                '.stage_builder_wizard_main',
                party_id=party.id,
                tournament_id=tournament.id,
            )
        if not is_stage_builder_preliminary_complete(state):
            return redirect_to(
                '.stage_builder_wizard_preliminary',
                party_id=party.id,
                tournament_id=tournament.id,
            )
        if not is_stage_builder_timing_complete(state):
            return redirect_to(
                '.stage_builder_wizard_timing',
                party_id=party.id,
                tournament_id=tournament.id,
            )

        try:
            generation_basis = str(state.get('generation_basis') or '').strip()
            main_stage_type = StageType(state['main_stage_type'])
            main_stage_size = int(state['main_stage_size'])
        except KeyError, TypeError, ValueError:
            flash_error(gettext('Ungültige Daten des Turnierplaners.'))
            return redirect_to(
                '.stage_builder_wizard_main',
                party_id=party.id,
                tournament_id=tournament.id,
            )

        max_players_per_match = state.get('max_players_per_match')
        if max_players_per_match in {'', None}:
            max_players_per_match = None
        else:
            try:
                max_players_per_match = int(max_players_per_match)
            except TypeError, ValueError:
                flash_error(
                    gettext('Ungültige Matchgröße für den Turnierplaner.')
                )
                return redirect_to(
                    '.stage_builder_wizard_main',
                    party_id=party.id,
                    tournament_id=tournament.id,
                )

        preliminary_type = None
        swiss_threshold = None
        if state.get('use_preliminary'):
            raw_preliminary_type = str(
                state.get('preliminary_type') or ''
            ).strip()
            if not raw_preliminary_type:
                flash_error(gettext('Bitte ein Vorrundenformat auswählen.'))
                return redirect_to(
                    '.stage_builder_wizard_preliminary',
                    party_id=party.id,
                    tournament_id=tournament.id,
                )

            try:
                preliminary_type = StageType(raw_preliminary_type)
            except ValueError:
                flash_error(gettext('Ungültiges Vorrundenformat.'))
                return redirect_to(
                    '.stage_builder_wizard_preliminary',
                    party_id=party.id,
                    tournament_id=tournament.id,
                )

            if preliminary_type == StageType.swiss:
                swiss_threshold = state.get('swiss_threshold')
                if swiss_threshold not in {2, 3, 4}:
                    flash_error(
                        gettext(
                            'Swiss-Vorrunden benötigen eine gültige Schwelle.'
                        )
                    )
                    return redirect_to(
                        '.stage_builder_wizard_preliminary',
                        party_id=party.id,
                        tournament_id=tournament.id,
                    )

        match build_stage_builder_plan(
            party.id,
            tournament.id,
            generation_basis=generation_basis,
            main_stage_type=main_stage_type,
            main_stage_size=main_stage_size,
            max_players_per_match=max_players_per_match,
            preliminary_type=preliminary_type,
            round_robin_builder_mode=state.get('round_robin_builder_mode'),
            round_robin_group_count=state.get('round_robin_group_count'),
            swiss_threshold=swiss_threshold,
            match_duration_minutes=state.get('match_duration_minutes'),
            max_matches_per_round=state.get('max_matches_per_round'),
            break_between_rounds_minutes=state.get(
                'break_between_rounds_minutes'
            ),
            initiator=g.user.as_user(),
        ):
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

    register_stage_create_routes(blueprint)
    register_stage_generation_routes(blueprint)
    register_stage_update_routes(blueprint)
    register_stage_participant_source_routes(blueprint)
    register_stage_delete_routes(blueprint)
